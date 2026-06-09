from pathlib import Path

from kellblog_audio.catalog import Catalog
from kellblog_audio.maintenance import reset_generated_audio


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
        audio_error="old",
        duration_sec=10,
        feed_published_at="2026-01-01T00:00:00+00:00",
    )
    cat.upsert_sitemap_entry("stale", "https://example.com/stale", None)
    cat.update_post("stale", audio_status="stale", audio_path=str(stale_path))
    cat.upsert_sitemap_entry("skip", "https://example.com/skip", None)
    cat.update_post("skip", audio_status="skip", audio_path=None)

    result = reset_generated_audio(cat, root=root, delete_files=True)

    assert result.reset_posts == 2
    assert result.deleted_files == 2
    assert not (root / done_path).exists()
    assert not (root / stale_path).exists()
    assert cat.get("done").audio_status == "pending"
    assert cat.get("done").audio_path is None
    assert cat.get("done").duration_sec is None
    assert cat.get("done").feed_published_at is None
    assert cat.get("skip").audio_status == "skip"
