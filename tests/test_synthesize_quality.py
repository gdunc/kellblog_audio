import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kellblog_audio import synthesize as synth
from kellblog_audio.catalog import Catalog, PostRow


def test_validate_audio_duration_rejects_implausibly_short_render():
    post = PostRow(
        slug="bad-render",
        url="https://example.com/bad-render",
        word_count=1200,
    )

    with pytest.raises(RuntimeError, match="Implausibly short audio"):
        synth.validate_audio_duration(post, duration_sec=240)


def test_validate_audio_duration_allows_reasonable_render():
    post = PostRow(
        slug="good-render",
        url="https://example.com/good-render",
        word_count=1200,
    )

    synth.validate_audio_duration(post, duration_sec=480)


def test_synthesize_batch_stops_on_first_qa_failure(monkeypatch):
    posts = [
        PostRow(slug="first", url="https://example.com/first", text="First"),
        PostRow(slug="second", url="https://example.com/second", text="Second"),
    ]

    class FakeCatalog:
        def __init__(self) -> None:
            self.errors: list[tuple[str, str]] = []

        def list_by_filter(self, *, audio_status=None, **_kwargs):
            return posts if audio_status == "pending" else []

        def update_post(self, slug, **fields):
            self.errors.append((slug, fields["audio_status"]))

    class FakeQAResult:
        passed = False
        reason = "coverage 10% < 70%"

    synthesized: list[str] = []
    monkeypatch.setattr(synth, "get_provider", lambda _name=None: object())
    monkeypatch.setattr(
        synth,
        "synthesize_post",
        lambda _catalog, slug, *_args, **_kwargs: synthesized.append(slug)
        or Path(f"/tmp/{slug}.mp3"),
    )
    monkeypatch.setattr(synth, "qa_post_audio", lambda _catalog, _slug: FakeQAResult())

    ok, err = synth.synthesize_batch(FakeCatalog(), qa_first=1)

    assert (ok, err) == (0, 1)
    assert synthesized == ["first"]


def test_synthesize_batch_marks_qa_failure_for_rerun(monkeypatch):
    posts = [
        PostRow(slug="first", url="https://example.com/first", text="First"),
    ]

    class FakeCatalog:
        def __init__(self) -> None:
            self.updated: list[tuple[str, dict]] = []

        def list_by_filter(self, *, audio_status=None, **_kwargs):
            return posts if audio_status == "pending" else []

        def update_post(self, slug, **fields):
            self.updated.append((slug, fields))

    class FakeQAResult:
        passed = False
        reason = "tail similarity 40% < 70%"

    catalog = FakeCatalog()
    monkeypatch.setattr(synth, "get_provider", lambda _name=None: object())
    monkeypatch.setattr(
        synth,
        "synthesize_post",
        lambda _catalog, slug, *_args, **_kwargs: Path(f"/tmp/{slug}.mp3"),
    )
    monkeypatch.setattr(synth, "qa_post_audio", lambda _catalog, _slug: FakeQAResult())

    synth.synthesize_batch(catalog, qa_first=1)

    assert catalog.updated == [
        (
            "first",
            {
                "audio_path": None,
                "audio_bytes": None,
                "audio_etag": None,
                "audio_status": "stale",
                "audio_error": "Audio QA failed; queued for rerun: tail similarity 40% < 70%",
                "duration_sec": None,
                "feed_published_at": None,
                "backfill_run_id": None,
            },
        )
    ]


def test_synthesize_batch_does_not_upload_failed_qa_audio(monkeypatch):
    posts = [
        PostRow(slug="first", url="https://example.com/first", text="First", year=2024),
    ]

    class FakeCatalog:
        def __init__(self) -> None:
            self.updated: list[tuple[str, dict]] = []

        def list_by_filter(self, *, audio_status=None, **_kwargs):
            return posts if audio_status == "pending" else []

        def update_post(self, slug, **fields):
            self.updated.append((slug, fields))

    class FakeQAResult:
        passed = False
        reason = "tail similarity 40% < 70%"

    catalog = FakeCatalog()
    audio_uploads: list[tuple[str, str]] = []
    monkeypatch.setattr(synth, "get_provider", lambda _name=None: object())
    monkeypatch.setattr(synth, "get_s3_client", lambda: object(), raising=False)
    monkeypatch.setattr(
        synth,
        "synthesize_post",
        lambda _catalog, slug, *_args, **_kwargs: Path(f"/tmp/{slug}.mp3"),
    )
    monkeypatch.setattr(synth, "qa_post_audio", lambda _catalog, _slug: FakeQAResult())
    monkeypatch.setattr(
        synth,
        "upload_file",
        lambda _client, local, key, content_type: audio_uploads.append((key, content_type)) or "etag-first",
        raising=False,
    )

    ok, err = synth.synthesize_batch(catalog, qa_first=1, upload_r2=True, run_id="run-1")

    assert (ok, err) == (0, 1)
    assert audio_uploads == []
    assert catalog.updated == [
        (
            "first",
            {
                "audio_path": None,
                "audio_bytes": None,
                "audio_etag": None,
                "audio_status": "stale",
                "audio_error": "Audio QA failed; queued for rerun: tail similarity 40% < 70%",
                "duration_sec": None,
                "feed_published_at": None,
                "backfill_run_id": None,
            },
        )
    ]


def test_distributed_synthesize_batch_requires_shard_metadata_for_manifest_output(tmp_path):
    with pytest.raises(ValueError, match="shard_index and shard_count are required"):
        synth.synthesize_batch(
            object(),
            run_id="run-1",
            manifest_out=tmp_path / "shard.json",
        )


def test_distributed_synthesize_batch_qa_halt_raises_before_manifest_write_or_upload(
    tmp_path, monkeypatch
):
    posts = [
        PostRow(slug="first", url="https://example.com/first", text="First", year=2024),
    ]

    class FakeCatalog:
        def __init__(self) -> None:
            self.updated: list[tuple[str, dict]] = []

        def list_by_filter(self, *, audio_status=None, **_kwargs):
            return posts if audio_status == "pending" else []

        def update_post(self, slug, **fields):
            self.updated.append((slug, fields))

    class FakeQAResult:
        passed = False
        reason = "tail similarity 40% < 70%"

    catalog = FakeCatalog()
    manifest_path = tmp_path / "shard.json"
    manifest_uploads: list[tuple[str, bytes, str]] = []
    monkeypatch.setattr(
        synth,
        "get_settings",
        lambda: SimpleNamespace(ensure_dirs=lambda: None),
    )
    monkeypatch.setattr(synth, "get_provider", lambda _name=None: object())
    monkeypatch.setattr(synth, "get_s3_client", lambda: object(), raising=False)
    monkeypatch.setattr(
        synth,
        "synthesize_post",
        lambda _catalog, slug, *_args, **_kwargs: Path(f"/tmp/{slug}.mp3"),
    )
    monkeypatch.setattr(synth, "qa_post_audio", lambda _catalog, _slug: FakeQAResult())
    monkeypatch.setattr(
        synth,
        "upload_bytes",
        lambda _client, payload, key, content_type: manifest_uploads.append((key, payload, content_type)),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="Distributed synthesize halted after QA failure"):
        synth.synthesize_batch(
            catalog,
            qa_first=1,
            shard_index=0,
            shard_count=1,
            run_id="run-1",
            manifest_out=manifest_path,
            manifest_r2_key="backfill/runs/run-1/manifests/shard-0-of-1.json",
        )

    assert manifest_uploads == []
    assert not manifest_path.exists()


def test_distributed_synthesize_batch_aborts_on_preexisting_stop_without_manifest(
    tmp_path, monkeypatch
):
    posts = [
        PostRow(slug="first", url="https://example.com/first", text="First", year=2024),
    ]

    class FakeCatalog:
        def list_by_filter(self, *, audio_status=None, **_kwargs):
            return posts if audio_status == "pending" else []

    manifest_path = tmp_path / "shard.json"
    manifest_uploads: list[tuple[str, bytes, str]] = []
    provider_calls: list[None] = []
    monkeypatch.setattr(
        synth,
        "get_settings",
        lambda: SimpleNamespace(ensure_dirs=lambda: None),
    )
    monkeypatch.setattr(
        synth,
        "get_provider",
        lambda _name=None: provider_calls.append(None) or object(),
    )
    monkeypatch.setattr(synth, "get_s3_client", lambda: object(), raising=False)
    monkeypatch.setattr(
        synth,
        "upload_bytes",
        lambda _client, payload, key, content_type: manifest_uploads.append((key, payload, content_type)),
        raising=False,
    )

    synth._stop_requested.set()
    try:
        with pytest.raises(
            RuntimeError,
            match="Distributed synthesize stopped before completing the shard run",
        ):
            synth.synthesize_batch(
                FakeCatalog(),
                shard_index=0,
                shard_count=1,
                run_id="run-1",
                manifest_out=manifest_path,
                manifest_r2_key="backfill/runs/run-1/manifests/shard-0-of-1.json",
            )
    finally:
        synth._stop_requested.clear()

    assert provider_calls == []
    assert manifest_uploads == []
    assert not manifest_path.exists()


def test_synthesize_batch_writes_and_uploads_distributed_manifest(tmp_path, monkeypatch):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    cat.upsert_sitemap_entry("alpha", "https://example.com/alpha", None)
    cat.update_post(
        "alpha",
        title="Alpha",
        published_at="2024-01-01T00:00:00Z",
        year=2024,
        text="Alpha body",
        word_count=2,
        ingest_status="done",
        audio_status="pending",
    )

    audio_dir = tmp_path / "output" / "audio"
    settings = SimpleNamespace(root=tmp_path, ensure_dirs=lambda: audio_dir.mkdir(parents=True, exist_ok=True))
    manifest_path = tmp_path / "shard.json"
    audio_uploads: list[tuple[str, str]] = []
    manifest_uploads: list[tuple[str, bytes, str]] = []

    monkeypatch.setattr(synth, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(synth, "get_settings", lambda: settings)
    monkeypatch.setattr(synth, "get_provider", lambda _name=None: SimpleNamespace(name="fake"))
    monkeypatch.setattr(synth, "get_s3_client", lambda: object(), raising=False)
    monkeypatch.setattr(
        synth,
        "upload_file",
        lambda _client, local, key, content_type: audio_uploads.append((key, content_type)) or "etag-alpha",
        raising=False,
    )
    monkeypatch.setattr(
        synth,
        "upload_bytes",
        lambda _client, payload, key, content_type: manifest_uploads.append((key, payload, content_type)),
        raising=False,
    )

    def fake_synthesize_post(catalog, slug, *_args, **_kwargs):
        out_path = audio_dir / "2024" / f"{slug}.mp3"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp3-bytes")
        catalog.update_post(
            slug,
            audio_path=str(out_path.relative_to(tmp_path)),
            audio_bytes=out_path.stat().st_size,
            audio_status="done",
            audio_error=None,
            duration_sec=123,
        )
        return out_path

    monkeypatch.setattr(synth, "synthesize_post", fake_synthesize_post)

    ok, err = synth.synthesize_batch(
        cat,
        shard_index=0,
        shard_count=1,
        run_id="run-1",
        manifest_out=manifest_path,
        manifest_r2_key="backfill/runs/run-1/manifests/shard-0-of-1.json",
        upload_r2=True,
    )

    assert (ok, err) == (1, 0)
    assert audio_uploads == [("audio/2024/alpha.mp3", "audio/mpeg")]
    assert manifest_uploads[0][0] == "backfill/runs/run-1/manifests/shard-0-of-1.json"
    assert manifest_uploads[0][2] == "application/json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "run-1"
    assert manifest["counts"] == {"done": 1, "error": 0, "skipped": 0}
    assert manifest["items"] == [
        {
            "audio_bytes": len(b"mp3-bytes"),
            "audio_etag": "etag-alpha",
            "audio_path": "output/audio/2024/alpha.mp3",
            "duration_sec": 123,
            "slug": "alpha",
            "status": "done",
            "year": 2024,
        }
    ]
