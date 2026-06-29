import tempfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from kellblog_audio import podcast, synthesize as synth
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


def test_build_feed_omits_skipped_external_audio_items_and_links_homepage():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.sqlite"
        cat = Catalog(db)
        cat.init_schema()
        cat.upsert_sitemap_entry("done-post", "https://www.kellblog.com/done-post/", None)
        cat.update_post(
            "done-post",
            title="Done Post",
            published_at="2024-06-01T12:00:00.000Z",
            year=2024,
            url="https://www.kellblog.com/done-post/",
            rss_excerpt="An excerpt about startups.",
            text="Body text for TTS.",
            word_count=3,
            content_hash="abc",
            ingest_status="done",
            audio_status="done",
            duration_sec=120,
            episode_in_season=1,
            audio_path="output/audio/2024/done-post.mp3",
        )
        cat.upsert_sitemap_entry("skip-post", "https://www.kellblog.com/skip-post/", None)
        cat.update_post(
            "skip-post",
            title="Skip Post",
            published_at="2024-06-02T12:00:00.000Z",
            year=2024,
            url="https://www.kellblog.com/skip-post/",
            rss_excerpt="External audio only.",
            text="Body text for TTS.",
            word_count=4,
            content_hash="def",
            ingest_status="done",
            audio_status="skip",
            duration_sec=None,
            episode_in_season=2,
        )

        root = ET.fromstring(build_feed(cat, local_audio=False))
        channel = root.find("channel")
        assert channel is not None
        items = channel.findall("item")

        assert channel.findtext("link") == "https://kellblog.thisisgrant.com"
        assert [item.findtext("title") for item in items] == ["Done Post"]
        assert items[0].find("enclosure") is not None


def test_build_feed_uses_persisted_audio_bytes_from_synthesized_post_when_local_file_is_missing(
    tmp_path, monkeypatch
):
    cat = Catalog(tmp_path / "test.sqlite")
    cat.init_schema()
    cat.upsert_sitemap_entry("remote-post", "https://www.kellblog.com/remote-post/", None)
    cat.update_post(
        "remote-post",
        title="Remote Post",
        published_at="2024-06-01T12:00:00.000Z",
        year=2024,
        url="https://www.kellblog.com/remote-post/",
        rss_excerpt="Remote audio.",
        text="Body text for TTS.",
        word_count=4,
        content_hash="abc",
        ingest_status="done",
        episode_in_season=1,
    )

    settings = SimpleNamespace(root=tmp_path)
    expected_bytes = len(b"persisted-mp3")

    monkeypatch.setattr(synth, "AUDIO_DIR", tmp_path / "output" / "audio")
    monkeypatch.setattr(synth, "get_settings", lambda: settings)
    monkeypatch.setattr(podcast, "get_settings", lambda: settings)
    monkeypatch.setattr(
        synth,
        "synthesize_text_to_wav",
        lambda _provider, _text, out_wav: out_wav.write_bytes(b"wav"),
    )
    monkeypatch.setattr(
        synth,
        "synthesize_outro_to_wav",
        lambda _provider, out_wav: out_wav.write_bytes(b"outro"),
    )

    def fake_merge_audio_parts(_parts, out_mp3, **_kwargs):
        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        out_mp3.write_bytes(b"persisted-mp3")
        return 120

    monkeypatch.setattr(synth, "merge_audio_parts", fake_merge_audio_parts)

    audio_path = synth.synthesize_post(cat, "remote-post", provider=object())
    post = cat.get("remote-post")

    assert audio_path is not None
    assert post is not None
    assert post.audio_bytes == expected_bytes

    audio_path.unlink()

    root = ET.fromstring(build_feed(cat, local_audio=False))
    enclosure = root.find("./channel/item/enclosure")

    assert enclosure is not None
    assert enclosure.attrib["length"] == str(expected_bytes)
