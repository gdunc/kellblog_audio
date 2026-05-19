import tempfile
from pathlib import Path

from kellblog_audio.catalog import Catalog
from kellblog_audio.podcast import build_feed, episode_guid


def test_episode_guid_stable():
    assert episode_guid("foo") == episode_guid("foo")
    assert len(episode_guid("foo")) == 64


def test_build_feed_contains_itunes_season():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.sqlite"
        cat = Catalog(db)
        cat.init_schema()
        cat.upsert_sitemap_entry("test-post", "https://www.kellblog.com/test-post/", None)
        cat.update_post(
            "test-post",
            title="Test Post",
            published_at="2024-06-01T12:00:00.000Z",
            year=2024,
            url="https://www.kellblog.com/test-post/",
            rss_excerpt="An excerpt about startups.",
            text="Body text for TTS.",
            word_count=3,
            content_hash="abc",
            ingest_status="done",
            audio_status="done",
            duration_sec=120,
            episode_in_season=1,
            audio_path="output/audio/2024/test-post.mp3",
        )
        xml = build_feed(cat, local_audio=True)
        assert "Kellblog Audio" in xml
        assert "itunes:season" in xml or "season" in xml.lower()
        assert "Test Post" in xml
        assert "thisisgrant.com" in xml
        assert episode_guid("test-post") in xml
