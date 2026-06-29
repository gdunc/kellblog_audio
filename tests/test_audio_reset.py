from pathlib import Path

from kellblog_audio.catalog import Catalog
from kellblog_audio.maintenance import reset_generated_audio
from kellblog_audio.qa import queue_audio_rerun


def test_reset_generated_audio_removes_files_and_preserves_skip(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()
    root = tmp_path

    done_path = Path("output/audio/2024/done.mp3")
    stale_path = Path("output/audio/2024/stale.mp3")
    for rel_path in (done_path, stale_path):
        full_path = root / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(b"bad audio")

    cat.upsert_sitemap_entry("done", "https://example.com/done", None)
    cat.update_post(
        "done",
        audio_status="done",
        audio_path=str(done_path),
        audio_bytes=1234,
        audio_etag="etag-done",
        audio_error="old",
        duration_sec=10,
        feed_published_at="2026-01-01T00:00:00+00:00",
        backfill_run_id="run-done",
    )
    cat.upsert_sitemap_entry("stale", "https://example.com/stale", None)
    cat.update_post(
        "stale",
        audio_status="stale",
        audio_path=str(stale_path),
        audio_bytes=5678,
        audio_etag="etag-stale",
        duration_sec=11,
        backfill_run_id="run-stale",
    )
    cat.upsert_sitemap_entry("skip", "https://example.com/skip", None)
    cat.update_post("skip", audio_status="skip", audio_path=None)

    result = reset_generated_audio(cat, root=root, delete_files=True)

    assert result.reset_posts == 2
    assert result.deleted_files == 2
    assert not (root / done_path).exists()
    assert not (root / stale_path).exists()
    assert cat.get("done").audio_status == "pending"
    assert cat.get("done").audio_path is None
    assert cat.get("done").audio_bytes is None
    assert cat.get("done").audio_etag is None
    assert cat.get("done").duration_sec is None
    assert cat.get("done").feed_published_at is None
    assert cat.get("done").backfill_run_id is None
    assert cat.get("stale").audio_path is None
    assert cat.get("stale").audio_bytes is None
    assert cat.get("stale").audio_etag is None
    assert cat.get("stale").duration_sec is None
    assert cat.get("stale").backfill_run_id is None
    assert cat.get("skip").audio_status == "skip"


def test_queue_audio_rerun_clears_generated_audio_metadata(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    cat.init_schema()

    cat.upsert_sitemap_entry("done", "https://example.com/done", None)
    cat.update_post(
        "done",
        audio_status="done",
        audio_path="output/audio/2024/done.mp3",
        audio_bytes=4321,
        audio_etag="etag-done",
        audio_error=None,
        duration_sec=123,
        feed_published_at="2026-01-01T00:00:00+00:00",
        backfill_run_id="run-1",
    )

    queue_audio_rerun(cat, "done", "tail similarity 40% < 70%")

    post = cat.get("done")
    assert post is not None
    assert post.audio_status == "stale"
    assert post.audio_path is None
    assert post.audio_bytes is None
    assert post.audio_etag is None
    assert post.audio_error == "Audio QA failed; queued for rerun: tail similarity 40% < 70%"
    assert post.duration_sec is None
    assert post.feed_published_at is None
    assert post.backfill_run_id is None
