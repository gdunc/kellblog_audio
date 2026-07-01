import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from kellblog_audio import publish as publish_mod
from kellblog_audio.catalog import Catalog
from kellblog_audio.config import R2_BUCKET
from kellblog_audio.distributed_backfill import (
    BackfillAutoRestartPlan,
    ShardManifestSnapshot,
    ShardProgress,
    ShardManifest,
    ShardManifestItem,
    create_backfill_baseline,
    prepare_backfill_baseline,
    plan_backfill_run,
    plan_backfill_auto_restart,
    read_shard_checkpoint,
    read_backfill_progress,
    read_backfill_manifest_state,
    seed_backfill_baseline_from_local_catalog,
    seed_backfill_baseline_from_run_catalog,
    merge_shard_manifests,
    shard_checkpoint_key,
    shard_progress_key,
)
from kellblog_audio.publish import backup_catalog, restore_catalog


OLD_SCHEMA = """
CREATE TABLE posts (
    slug TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    year INTEGER,
    rss_excerpt TEXT,
    categories TEXT,
    body_raw TEXT,
    text TEXT,
    word_count INTEGER,
    content_hash TEXT,
    sitemap_lastmod TEXT,
    etag TEXT,
    last_modified TEXT,
    ingest_status TEXT DEFAULT 'pending',
    ingest_error TEXT,
    audio_path TEXT,
    audio_status TEXT DEFAULT 'pending',
    audio_error TEXT,
    duration_sec INTEGER,
    episode_in_season INTEGER,
    feed_published_at TEXT,
    skip_reason TEXT
);
"""


def test_init_schema_adds_backfill_audio_metadata_columns_to_existing_catalog(tmp_path):
    db = tmp_path / "catalog.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(OLD_SCHEMA)

    cat = Catalog(db)
    cat.init_schema()
    cat.upsert_sitemap_entry("post", "https://example.com/post", None)
    cat.update_post(
        "post",
        audio_bytes=1234,
        audio_etag="etag-1",
        backfill_run_id="run-1",
    )

    post = cat.get("post")
    assert post is not None
    assert post.audio_bytes == 1234
    assert post.audio_etag == "etag-1"
    assert post.backfill_run_id == "run-1"


def test_backup_and_restore_catalog_accept_explicit_r2_keys_and_replace_stale_sidecars(
    tmp_path, monkeypatch
):
    class FakeS3Client:
        def __init__(self) -> None:
            self.upload_calls = []
            self.download_calls = []

        def upload_file(self, filename, bucket, key, ExtraArgs=None):
            self.upload_calls.append((filename, bucket, key, ExtraArgs))

        def download_file(self, bucket, key, filename):
            self.download_calls.append((bucket, key, filename))
            with open(filename, "wb") as fh:
                fh.write(b"restored")

    client = FakeS3Client()
    monkeypatch.setattr("kellblog_audio.publish.get_s3_client", lambda: client)

    db = tmp_path / "catalog.sqlite"
    cat = Catalog(db)
    cat.init_schema()

    key = "backfill/runs/r1/baseline/catalog.sqlite"
    assert backup_catalog(cat, key=key) == key
    assert client.upload_calls[0][2] == key

    restored = Catalog(tmp_path / "restored" / "catalog.sqlite")
    restored.path.write_bytes(b"stale")
    wal_path = restored.path.with_name(f"{restored.path.name}-wal")
    shm_path = restored.path.with_name(f"{restored.path.name}-shm")
    wal_path.write_bytes(b"stale wal")
    shm_path.write_bytes(b"stale shm")

    assert restore_catalog(restored, key=key) is True

    assert len(client.download_calls) == 1
    bucket, downloaded_key, download_target = client.download_calls[0]
    assert (bucket, downloaded_key) == (R2_BUCKET, key)
    assert Path(download_target).parent == restored.path.parent
    assert Path(download_target) != restored.path
    assert not Path(download_target).exists()
    assert restored.path.read_bytes() == b"restored"
    assert not wal_path.exists()
    assert not shm_path.exists()


def test_backup_catalog_snapshots_wal_commits_before_upload(tmp_path, monkeypatch):
    class FakeS3Client:
        def __init__(self) -> None:
            self.uploaded_path = tmp_path / "uploaded.sqlite"

        def upload_file(self, filename, bucket, key, ExtraArgs=None):
            self.uploaded_path.write_bytes(Path(filename).read_bytes())

    client = FakeS3Client()
    monkeypatch.setattr("kellblog_audio.publish.get_s3_client", lambda: client)

    db = tmp_path / "catalog.sqlite"
    cat = Catalog(db)
    cat.init_schema()

    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute(
            "INSERT INTO posts (slug, url, title, ingest_status) VALUES (?, ?, ?, 'done')",
            ("wal-post", "https://example.com/wal-post", "WAL Post"),
        )

    unsafe_copy = tmp_path / "unsafe-main.sqlite"
    unsafe_copy.write_bytes(db.read_bytes())
    with sqlite3.connect(unsafe_copy) as conn:
        missing = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE slug = ?",
            ("wal-post",),
        ).fetchone()[0]
    assert missing == 0

    backup_catalog(cat, key="backfill/runs/r1/baseline/catalog.sqlite")

    with sqlite3.connect(client.uploaded_path) as conn:
        present = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE slug = ?",
            ("wal-post",),
        ).fetchone()[0]
    assert present == 1


def test_publish_to_r2_skip_audio_marks_done_rows_feed_published(tmp_path, monkeypatch):
    class FakeS3Client:
        def __init__(self) -> None:
            self.uploaded_keys: list[str] = []

        def upload_file(self, filename, bucket, key, ExtraArgs=None):
            self.uploaded_keys.append(key)

        def copy_object(self, **kwargs):
            return kwargs

        def delete_object(self, **kwargs):
            return kwargs

    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    _seed_post(cat, "alpha")
    cat.update_post(
        "alpha",
        audio_status="done",
        audio_path="output/audio/2024/alpha.mp3",
        audio_bytes=1234,
        duration_sec=120,
    )

    review_page = tmp_path / "review" / "index.html"
    review_page.parent.mkdir(parents=True, exist_ok=True)
    review_page.write_text("<html>review</html>", encoding="utf-8")

    client = FakeS3Client()
    monkeypatch.setattr("kellblog_audio.publish.get_s3_client", lambda: client)
    monkeypatch.setattr(publish_mod, "FEEDS_DIR", tmp_path / "feeds")
    monkeypatch.setattr(
        publish_mod,
        "get_settings",
        lambda: SimpleNamespace(root=tmp_path, ensure_dirs=lambda: None),
    )
    monkeypatch.setattr(publish_mod, "write_review_page", lambda _catalog: review_page)

    url = publish_mod.publish_to_r2(cat, upload_audio=False)

    assert url.endswith("/feed.xml")
    assert all(not key.startswith("audio/") for key in client.uploaded_keys)
    assert cat.get("alpha").feed_published_at is not None


def _seed_post(cat: Catalog, slug: str) -> None:
    cat.upsert_sitemap_entry(slug, f"https://example.com/{slug}", None)
    cat.update_post(
        slug,
        title=slug.replace("-", " ").title(),
        published_at="2024-01-01T00:00:00Z",
        year=2024,
        text="Body text for synthesis.",
        word_count=4,
        ingest_status="done",
        audio_status="pending",
    )


def test_create_backfill_baseline_runs_ingest_and_uses_run_scoped_key(
    tmp_path, monkeypatch
):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()

    calls: dict[str, list[object]] = {"ingest": [], "backup": []}

    def fake_ingest_all(arg: Catalog) -> Catalog:
        calls["ingest"].append(arg)
        return arg

    def fake_backup_catalog(arg: Catalog, *, key: str | None = None) -> str:
        calls["backup"].append((arg, key))
        return key or ""

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.ingest_all",
        fake_ingest_all,
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.backup_catalog",
        fake_backup_catalog,
    )

    key = create_backfill_baseline(cat, run_id="r1")

    assert key == "backfill/runs/r1/baseline/catalog.sqlite"
    assert calls == {
        "ingest": [cat],
        "backup": [(cat, "backfill/runs/r1/baseline/catalog.sqlite")],
    }


def test_prepare_backfill_baseline_resume_restores_existing_run_scoped_key(
    tmp_path, monkeypatch
):
    cat = Catalog(tmp_path / "catalog.sqlite")
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.restore_catalog",
        lambda catalog, key=None: calls.append(("restore", key)) or True,
    )
    monkeypatch.setattr(
        cat,
        "init_schema",
        lambda: calls.append(("init_schema", cat.path)),
    )

    key = prepare_backfill_baseline(cat, run_id="r1", resume=True)

    assert key == "backfill/runs/r1/baseline/catalog.sqlite"
    assert calls == [
        ("restore", "backfill/runs/r1/baseline/catalog.sqlite"),
        ("init_schema", cat.path),
    ]


def test_prepare_backfill_baseline_resume_rejects_missing_baseline(tmp_path, monkeypatch):
    cat = Catalog(tmp_path / "catalog.sqlite")
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.restore_catalog",
        lambda catalog, key=None: False,
    )

    with pytest.raises(ValueError, match="no baseline catalog found"):
        prepare_backfill_baseline(cat, run_id="r1", resume=True)


def test_seed_backfill_baseline_from_local_catalog_uploads_done_audio_and_backs_up(
    tmp_path, monkeypatch
):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    _seed_post(cat, "alpha")
    _seed_post(cat, "beta")

    audio_dir = tmp_path / "output" / "audio" / "2024"
    audio_dir.mkdir(parents=True)
    alpha_mp3 = audio_dir / "alpha.mp3"
    alpha_mp3.write_bytes(b"alpha-audio")

    cat.update_post(
        "alpha",
        audio_status="done",
        audio_path="output/audio/2024/alpha.mp3",
        audio_bytes=alpha_mp3.stat().st_size,
        duration_sec=120,
    )

    uploads: list[tuple[str, str, str]] = []
    backup_calls: list[tuple[Catalog, str | None]] = []

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.ingest_all",
        lambda catalog: catalog,
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.get_settings",
        lambda: SimpleNamespace(root=tmp_path),
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.get_s3_client",
        lambda: object(),
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.upload_file",
        lambda client, local, key, content_type: uploads.append((str(local), key, content_type)) or "etag-alpha",
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.backup_catalog",
        lambda catalog, *, key=None: backup_calls.append((catalog, key)) or (key or ""),
    )

    result = seed_backfill_baseline_from_local_catalog(cat, run_id="r1")

    assert result.run_id == "r1"
    assert result.uploaded == 1
    assert result.baseline_key == "backfill/runs/r1/baseline/catalog.sqlite"
    assert uploads == [
        (str(alpha_mp3), "audio/2024/alpha.mp3", "audio/mpeg"),
    ]
    assert backup_calls == [(cat, "backfill/runs/r1/baseline/catalog.sqlite")]

    alpha = cat.get("alpha")
    beta = cat.get("beta")
    assert alpha is not None and beta is not None
    assert alpha.audio_etag == "etag-alpha"
    assert alpha.backfill_run_id == "r1"
    assert beta.backfill_run_id is None


def test_seed_backfill_baseline_from_local_catalog_requeues_error_rows_for_retry(
    tmp_path, monkeypatch
):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    _seed_post(cat, "alpha")
    _seed_post(cat, "beta")

    audio_dir = tmp_path / "output" / "audio" / "2024"
    audio_dir.mkdir(parents=True)
    alpha_mp3 = audio_dir / "alpha.mp3"
    alpha_mp3.write_bytes(b"alpha-audio")

    cat.update_post(
        "alpha",
        audio_status="done",
        audio_path="output/audio/2024/alpha.mp3",
        audio_bytes=alpha_mp3.stat().st_size,
        duration_sec=120,
    )
    cat.update_post(
        "beta",
        audio_status="error",
        audio_error="broken pipe",
        audio_path="output/audio/2024/beta.mp3",
        audio_bytes=999,
        duration_sec=42,
        audio_etag="etag-beta",
        backfill_run_id="old-run",
    )

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.ingest_all",
        lambda catalog: catalog,
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.get_settings",
        lambda: SimpleNamespace(root=tmp_path),
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.get_s3_client",
        lambda: object(),
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.upload_file",
        lambda *_args, **_kwargs: "etag-alpha",
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.backup_catalog",
        lambda catalog, *, key=None: key or "",
    )

    result = seed_backfill_baseline_from_local_catalog(
        cat,
        run_id="r1",
        retry_errors=True,
    )

    assert result.requeued_errors == 1

    beta = cat.get("beta")
    assert beta is not None
    assert beta.audio_status == "stale"
    assert beta.audio_error is None
    assert beta.audio_path is None
    assert beta.audio_bytes is None
    assert beta.duration_sec is None
    assert beta.audio_etag is None
    assert beta.backfill_run_id is None


def test_seed_backfill_baseline_from_run_catalog_restores_final_catalog_and_requeues_errors(
    tmp_path, monkeypatch
):
    cat = Catalog(tmp_path / "catalog.sqlite")
    calls: list[tuple[str, object]] = []

    def fake_restore(catalog, key=None):
        calls.append(("restore", key))
        catalog.init_schema()
        _seed_post(catalog, "done-post")
        _seed_post(catalog, "error-post")
        catalog.update_post(
            "done-post",
            audio_status="done",
            audio_path="output/audio/2024/done-post.mp3",
            audio_bytes=1234,
            duration_sec=120,
            audio_etag="etag-done",
            backfill_run_id="old-run",
        )
        catalog.update_post(
            "error-post",
            audio_status="error",
            audio_error="NoneType callable",
            audio_path="output/audio/2024/error-post.mp3",
            audio_bytes=111,
            duration_sec=12,
            audio_etag="etag-error",
            backfill_run_id="old-run",
        )
        return True

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.restore_catalog",
        fake_restore,
    )
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.backup_catalog",
        lambda catalog, *, key=None: calls.append(("backup", key)) or (key or ""),
    )

    result = seed_backfill_baseline_from_run_catalog(
        cat,
        run_id="new-run",
        source_run_id="old-run",
    )

    assert result.run_id == "new-run"
    assert result.uploaded == 0
    assert result.requeued_errors == 1
    assert result.baseline_key == "backfill/runs/new-run/baseline/catalog.sqlite"
    assert calls == [
        ("restore", "backfill/runs/old-run/catalog/final.sqlite"),
        ("backup", "backfill/runs/new-run/baseline/catalog.sqlite"),
    ]

    done_post = cat.get("done-post")
    error_post = cat.get("error-post")
    assert done_post is not None and error_post is not None
    assert done_post.audio_status == "done"
    assert done_post.backfill_run_id == "old-run"
    assert error_post.audio_status == "stale"
    assert error_post.audio_error is None
    assert error_post.audio_path is None
    assert error_post.audio_bytes is None
    assert error_post.duration_sec is None
    assert error_post.audio_etag is None
    assert error_post.backfill_run_id is None


def test_shard_progress_key_uses_run_scoped_progress_prefix():
    assert shard_progress_key("run-1", 2, 6) == "backfill/runs/run-1/progress/shard-2-of-6.json"


def test_shard_checkpoint_key_uses_run_scoped_checkpoint_prefix():
    assert (
        shard_checkpoint_key("run-1", 2, 6)
        == "backfill/runs/run-1/checkpoints/shard-2-of-6.json"
    )


def test_read_shard_checkpoint_returns_manifest_when_present(monkeypatch):
    checkpoint = ShardManifest(
        run_id="run-1",
        shard_index=1,
        shard_count=4,
        provider="chatterbox",
        items=[
            ShardManifestItem(
                slug="alpha",
                year=2024,
                status="done",
                audio_path="output/audio/2024/alpha.mp3",
                duration_sec=120,
                audio_bytes=1234,
                audio_etag="etag-alpha",
            )
        ],
    )

    class FakeBody:
        def read(self) -> bytes:
            return checkpoint.to_json().encode("utf-8")

    class FakeS3Client:
        def get_object(self, *, Bucket, Key):
            assert Bucket == R2_BUCKET
            assert Key == shard_checkpoint_key("run-1", 1, 4)
            return {"Body": FakeBody()}

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.get_s3_client",
        lambda: FakeS3Client(),
    )

    loaded = read_shard_checkpoint("run-1", 1, 4)

    assert loaded == checkpoint


def test_read_shard_checkpoint_returns_none_when_missing(monkeypatch):
    class FakeS3Client:
        def get_object(self, *, Bucket, Key):
            raise RuntimeError("NoSuchKey")

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.get_s3_client",
        lambda: FakeS3Client(),
    )

    assert read_shard_checkpoint("run-1", 1, 4) is None


def test_read_backfill_progress_aggregates_per_shard_progress(monkeypatch):
    shard0 = ShardProgress(
        run_id="run-1",
        shard_index=0,
        shard_count=2,
        provider="chatterbox",
        started_at="2026-06-29T15:00:00Z",
        updated_at="2026-06-29T15:05:00Z",
        assigned_count=10,
        processed_count=5,
        counts={"done": 4, "error": 1, "skipped": 0},
        last_slug="alpha",
        last_status="error",
        complete=False,
    )
    shard1 = ShardProgress(
        run_id="run-1",
        shard_index=1,
        shard_count=2,
        provider="chatterbox",
        started_at="2026-06-29T15:00:00Z",
        updated_at="2026-06-29T15:06:00Z",
        finished_at="2026-06-29T15:06:00Z",
        assigned_count=9,
        processed_count=9,
        counts={"done": 9, "error": 0, "skipped": 0},
        last_slug="omega",
        last_status="done",
        complete=True,
    )

    payloads = {
        shard_progress_key("run-1", 0, 2): shard0.to_json().encode("utf-8"),
        shard_progress_key("run-1", 1, 2): shard1.to_json().encode("utf-8"),
    }

    class FakePaginator:
        def paginate(self, **_kwargs):
            return [{"Contents": [{"Key": key} for key in sorted(payloads)]}]

    class FakeBody:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

    class FakeS3Client:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return FakePaginator()

        def get_object(self, *, Bucket, Key):
            assert Bucket == R2_BUCKET
            return {"Body": FakeBody(payloads[Key])}

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.get_s3_client",
        lambda: FakeS3Client(),
    )

    snapshot = read_backfill_progress("run-1")

    assert snapshot.run_id == "run-1"
    assert snapshot.shard_count == 2
    assert snapshot.assigned_count == 19
    assert snapshot.processed_count == 14
    assert snapshot.counts == {"done": 13, "error": 1, "skipped": 0}
    assert [progress.shard_index for progress in snapshot.shards] == [0, 1]
    assert snapshot.shards[0].complete is False
    assert snapshot.shards[1].complete is True


def test_read_backfill_progress_rejects_missing_run_progress(monkeypatch):
    class FakePaginator:
        def paginate(self, **_kwargs):
            return [{"Contents": []}]

    class FakeS3Client:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return FakePaginator()

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.get_s3_client",
        lambda: FakeS3Client(),
    )

    with pytest.raises(ValueError, match="no shard progress found"):
        read_backfill_progress("run-1")


def test_read_backfill_manifest_state_reports_found_missing_and_unexpected(monkeypatch):
    keys = [
        "backfill/runs/run-1/manifests/notes.txt",
        "backfill/runs/run-1/manifests/shard-0-of-3.json",
        "backfill/runs/run-1/manifests/shard-1-of-4.json",
        "backfill/runs/run-1/manifests/shard-2-of-3.json",
    ]

    class FakePaginator:
        def paginate(self, **_kwargs):
            return [{"Contents": [{"Key": key} for key in keys]}]

    class FakeS3Client:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return FakePaginator()

    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.get_s3_client",
        lambda: FakeS3Client(),
    )

    snapshot = read_backfill_manifest_state("run-1", 3)

    assert snapshot == ShardManifestSnapshot(
        run_id="run-1",
        shard_count=3,
        found_shards=[0, 2],
        missing_shards=[1],
        unexpected_keys=[
            "backfill/runs/run-1/manifests/notes.txt",
            "backfill/runs/run-1/manifests/shard-1-of-4.json",
        ],
    )


def test_plan_backfill_run_for_new_run_uses_all_missing_non_helper_shards():
    plan = plan_backfill_run(
        shard_count=6,
        qa_first=0,
        year="",
        local_helper_shards_raw="1, 4",
        github_run_id="12345",
        now=datetime(2026, 6, 30, 8, 0, 0, tzinfo=timezone.utc),
    )

    assert plan.run_id == "20260630T080000Z-12345"
    assert plan.resume_requested is False
    assert plan.local_helper_shards == [1, 4]
    assert plan.completed_shards == []
    assert plan.missing_shards == [0, 1, 2, 3, 4, 5]
    assert plan.gha_shards == [0, 2, 3, 5]


def test_plan_backfill_run_for_resume_only_schedules_missing_non_helper_shards(
    monkeypatch,
):
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.read_backfill_manifest_state",
        lambda run_id, shard_count: ShardManifestSnapshot(
            run_id=run_id,
            shard_count=shard_count,
            found_shards=[0, 2, 5],
            missing_shards=[1, 3, 4],
            unexpected_keys=[],
        ),
    )

    plan = plan_backfill_run(
        shard_count=6,
        qa_first=2,
        year="2024",
        local_helper_shards_raw="4",
        resume_run_id="resume-1",
    )

    assert plan.run_id == "resume-1"
    assert plan.resume_requested is True
    assert plan.completed_shards == [0, 2, 5]
    assert plan.missing_shards == [1, 3, 4]
    assert plan.gha_shards == [1, 3]


def test_plan_backfill_run_rejects_unexpected_manifest_keys(monkeypatch):
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.read_backfill_manifest_state",
        lambda run_id, shard_count: ShardManifestSnapshot(
            run_id=run_id,
            shard_count=shard_count,
            found_shards=[0],
            missing_shards=[1],
            unexpected_keys=["backfill/runs/resume-1/manifests/shard-0-of-99.json"],
        ),
    )

    with pytest.raises(ValueError, match="unexpected manifest keys"):
        plan_backfill_run(
            shard_count=2,
            qa_first=0,
            local_helper_shards_raw="",
            resume_run_id="resume-1",
        )


def test_plan_backfill_auto_restart_resumes_missing_non_helper_shards(monkeypatch):
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.plan_backfill_run",
        lambda **_kwargs: SimpleNamespace(
            gha_shards=[1, 3],
            missing_shards=[1, 2, 3],
        ),
    )

    plan = plan_backfill_auto_restart(
        run_id="run-1",
        shard_count=6,
        qa_first=0,
        local_helper_shards_raw="2",
        auto_resume=True,
        resume_depth=0,
        max_auto_resumes=5,
        summary_error_count=4,
    )

    assert plan == BackfillAutoRestartPlan(
        should_dispatch=True,
        mode="resume",
        reason="missing non-helper shard manifests: 1,3",
        next_resume_depth=1,
        gha_shards=[1, 3],
        missing_shards=[1, 2, 3],
        resume_run_id="run-1",
        seed_run_id=None,
    )


def test_plan_backfill_auto_restart_dispatches_retry_run_for_error_rows(monkeypatch):
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.plan_backfill_run",
        lambda **_kwargs: SimpleNamespace(
            gha_shards=[],
            missing_shards=[],
        ),
    )

    plan = plan_backfill_auto_restart(
        run_id="run-1",
        shard_count=6,
        qa_first=0,
        local_helper_shards_raw="",
        auto_resume=True,
        resume_depth=2,
        max_auto_resumes=5,
        summary_error_count=6,
    )

    assert plan == BackfillAutoRestartPlan(
        should_dispatch=True,
        mode="retry-errors",
        reason="manifest set complete but 6 error rows remain",
        next_resume_depth=3,
        gha_shards=[],
        missing_shards=[],
        resume_run_id=None,
        seed_run_id="run-1",
    )


def test_plan_backfill_auto_restart_stops_when_no_missing_shards_or_errors(monkeypatch):
    monkeypatch.setattr(
        "kellblog_audio.distributed_backfill.plan_backfill_run",
        lambda **_kwargs: SimpleNamespace(
            gha_shards=[],
            missing_shards=[],
        ),
    )

    plan = plan_backfill_auto_restart(
        run_id="run-1",
        shard_count=6,
        qa_first=0,
        local_helper_shards_raw="",
        auto_resume=True,
        resume_depth=1,
        max_auto_resumes=5,
        summary_error_count=0,
    )

    assert plan == BackfillAutoRestartPlan(
        should_dispatch=False,
        mode="none",
        reason="no missing non-helper shard manifests and no error rows remain",
        next_resume_depth=2,
        gha_shards=[],
        missing_shards=[],
        resume_run_id=None,
        seed_run_id=None,
    )


def test_merge_shard_manifests_applies_results_and_summarizes_counts(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    for slug in ("alpha", "beta", "gamma"):
        _seed_post(cat, slug)

    manifest0 = ShardManifest(
        run_id="r1",
        shard_index=0,
        shard_count=2,
        provider="test",
        items=[
            ShardManifestItem(
                slug="alpha",
                year=2024,
                status="done",
                audio_path="output/audio/2024/alpha.mp3",
                duration_sec=120,
                audio_bytes=1234,
                audio_etag="etag-alpha",
            ),
            ShardManifestItem(
                slug="beta",
                year=2024,
                status="error",
                error="synthesis failed",
            ),
        ],
    )
    manifest1 = ShardManifest(
        run_id="r1",
        shard_index=1,
        shard_count=2,
        provider="test",
        items=[
            ShardManifestItem(
                slug="gamma",
                year=2024,
                status="done",
                audio_path="output/audio/2024/gamma.mp3",
                duration_sec=95,
                audio_bytes=4321,
                audio_etag="etag-gamma",
            )
        ],
    )

    m0 = tmp_path / "shard-0.json"
    m1 = tmp_path / "shard-1.json"
    m0.write_text(manifest0.to_json(), encoding="utf-8")
    m1.write_text(manifest1.to_json(), encoding="utf-8")

    result = merge_shard_manifests(cat, run_id="r1", manifests=[m1, m0])

    assert result.done == 2
    assert result.errors == 1
    assert result.skipped == 0

    alpha = cat.get("alpha")
    beta = cat.get("beta")
    gamma = cat.get("gamma")
    assert alpha is not None and beta is not None and gamma is not None

    assert alpha.audio_status == "done"
    assert alpha.audio_path == "output/audio/2024/alpha.mp3"
    assert alpha.duration_sec == 120
    assert alpha.audio_bytes == 1234
    assert alpha.audio_etag == "etag-alpha"
    assert alpha.audio_error is None
    assert alpha.backfill_run_id == "r1"

    assert beta.audio_status == "error"
    assert beta.audio_error == "synthesis failed"

    assert gamma.audio_status == "done"
    assert gamma.audio_path == "output/audio/2024/gamma.mp3"
    assert gamma.duration_sec == 95
    assert gamma.audio_bytes == 4321
    assert gamma.audio_etag == "etag-gamma"
    assert gamma.backfill_run_id == "r1"


def test_merge_shard_manifests_rejects_duplicate_slugs(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    _seed_post(cat, "alpha")

    primary = ShardManifest(
        run_id="r1",
        shard_index=0,
        shard_count=2,
        provider="test",
        items=[
            ShardManifestItem(
                slug="alpha",
                year=2024,
                status="error",
                error="boom",
            )
        ],
    )
    duplicate = ShardManifest(
        run_id="r1",
        shard_index=1,
        shard_count=2,
        provider="test",
        items=[
            ShardManifestItem(
                slug="alpha",
                year=2024,
                status="done",
                audio_path="output/audio/2024/alpha.mp3",
                duration_sec=99,
                audio_bytes=111,
            )
        ],
    )

    p0 = tmp_path / "primary.json"
    p1 = tmp_path / "duplicate.json"
    p0.write_text(primary.to_json(), encoding="utf-8")
    p1.write_text(duplicate.to_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate slug"):
        merge_shard_manifests(cat, run_id="r1", manifests=[p0, p1])


def test_merge_shard_manifests_rejects_empty_manifest_list(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()

    with pytest.raises(ValueError, match="no shard manifests found"):
        merge_shard_manifests(cat, run_id="r1", manifests=[])


def test_merge_shard_manifests_rejects_missing_shard(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    for slug in ("alpha", "gamma"):
        _seed_post(cat, slug)

    manifest0 = ShardManifest(
        run_id="r1",
        shard_index=0,
        shard_count=3,
        provider="test",
        items=[ShardManifestItem(slug="alpha", year=2024, status="error", error="boom")],
    )
    manifest2 = ShardManifest(
        run_id="r1",
        shard_index=2,
        shard_count=3,
        provider="test",
        items=[ShardManifestItem(slug="gamma", year=2024, status="error", error="boom")],
    )

    p0 = tmp_path / "shard-0.json"
    p2 = tmp_path / "shard-2.json"
    p0.write_text(manifest0.to_json(), encoding="utf-8")
    p2.write_text(manifest2.to_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="missing shard manifests"):
        merge_shard_manifests(cat, run_id="r1", manifests=[p0, p2])


def test_merge_shard_manifests_rejects_duplicate_shard_index(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    for slug in ("alpha", "beta"):
        _seed_post(cat, slug)

    manifest0 = ShardManifest(
        run_id="r1",
        shard_index=0,
        shard_count=2,
        provider="test",
        items=[ShardManifestItem(slug="alpha", year=2024, status="error", error="boom")],
    )
    duplicate0 = ShardManifest(
        run_id="r1",
        shard_index=0,
        shard_count=2,
        provider="test",
        items=[ShardManifestItem(slug="beta", year=2024, status="error", error="boom")],
    )

    p0 = tmp_path / "shard-0a.json"
    p1 = tmp_path / "shard-0b.json"
    p0.write_text(manifest0.to_json(), encoding="utf-8")
    p1.write_text(duplicate0.to_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate shard_index"):
        merge_shard_manifests(cat, run_id="r1", manifests=[p0, p1])


def test_merge_shard_manifests_rejects_inconsistent_shard_count(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    for slug in ("alpha", "beta"):
        _seed_post(cat, slug)

    manifest0 = ShardManifest(
        run_id="r1",
        shard_index=0,
        shard_count=2,
        provider="test",
        items=[ShardManifestItem(slug="alpha", year=2024, status="error", error="boom")],
    )
    manifest1 = ShardManifest(
        run_id="r1",
        shard_index=1,
        shard_count=3,
        provider="test",
        items=[ShardManifestItem(slug="beta", year=2024, status="error", error="boom")],
    )

    p0 = tmp_path / "shard-0.json"
    p1 = tmp_path / "shard-1.json"
    p0.write_text(manifest0.to_json(), encoding="utf-8")
    p1.write_text(manifest1.to_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest shard_count mismatch"):
        merge_shard_manifests(cat, run_id="r1", manifests=[p0, p1])


def test_merge_shard_manifests_rejects_done_items_missing_required_fields(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    _seed_post(cat, "alpha")

    manifest_path = tmp_path / "malformed.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "r1",
                "shard_index": 0,
                "shard_count": 1,
                "items": [
                    {
                        "slug": "alpha",
                        "status": "done",
                        "audio_path": "output/audio/2024/alpha.mp3",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="done manifest item missing required fields"):
        merge_shard_manifests(cat, run_id="r1", manifests=[manifest_path])

    alpha = cat.get("alpha")
    assert alpha is not None
    assert alpha.audio_status == "pending"
    assert alpha.audio_path is None
    assert alpha.backfill_run_id is None


def test_merge_shard_manifests_rolls_back_all_updates_on_apply_failure(
    tmp_path, monkeypatch
):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    for slug in ("alpha", "beta"):
        _seed_post(cat, slug)

    manifest = ShardManifest(
        run_id="r1",
        shard_index=0,
        shard_count=1,
        provider="test",
        items=[
            ShardManifestItem(
                slug="alpha",
                year=2024,
                status="done",
                audio_path="output/audio/2024/alpha.mp3",
                duration_sec=120,
                audio_bytes=1234,
            ),
            ShardManifestItem(
                slug="beta",
                year=2024,
                status="done",
                audio_path="output/audio/2024/beta.mp3",
                duration_sec=90,
                audio_bytes=4321,
            ),
        ],
    )
    manifest_path = tmp_path / "shard.json"
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")

    original_connect = cat.connect

    class FailingConnection:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn
            self._update_calls = 0

        def execute(self, sql: str, params=()):
            if sql.lstrip().upper().startswith("UPDATE POSTS SET"):
                self._update_calls += 1
                if self._update_calls == 2:
                    raise sqlite3.OperationalError("simulated second row failure")
            return self._conn.execute(sql, params)

        def __getattr__(self, name: str):
            return getattr(self._conn, name)

    @contextmanager
    def flaky_connect():
        with original_connect() as conn:
            yield FailingConnection(conn)

    monkeypatch.setattr(cat, "connect", flaky_connect)

    with pytest.raises(sqlite3.OperationalError, match="simulated second row failure"):
        merge_shard_manifests(cat, run_id="r1", manifests=[manifest_path])

    alpha = cat.get("alpha")
    beta = cat.get("beta")
    assert alpha is not None and beta is not None
    assert alpha.audio_status == "pending"
    assert alpha.audio_path is None
    assert alpha.backfill_run_id is None
    assert beta.audio_status == "pending"
    assert beta.audio_path is None
    assert beta.backfill_run_id is None
