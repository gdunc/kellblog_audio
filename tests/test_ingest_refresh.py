from types import SimpleNamespace

import httpx

from kellblog_audio import ingest
from kellblog_audio.catalog import Catalog
from kellblog_audio.extract import content_hash


class FakeClient:
    def get(self, url, **kwargs):
        request = httpx.Request("GET", url)
        if url == ingest.RSS_URL:
            return httpx.Response(200, text="<rss><channel /></rss>", request=request)
        return httpx.Response(200, text="<html></html>", request=request)


def _catalog_with_done_post(tmp_path, *, text: str, hash_value: str):
    cat = Catalog(tmp_path / "test.sqlite")
    cat.init_schema()
    cat.upsert_sitemap_entry("test-post", "https://www.kellblog.com/test-post/", None)
    cat.update_post(
        "test-post",
        title="Test Post",
        published_at="2024-06-01T12:00:00.000Z",
        year=2024,
        body_raw="Body",
        text=text,
        word_count=len(text.split()),
        content_hash=hash_value,
        ingest_status="done",
        audio_status="done",
        audio_path="output/audio/2024/test-post.mp3",
        duration_sec=120,
    )
    return cat


def test_ingest_refresh_marks_done_audio_stale_when_cleaned_text_changes(tmp_path, monkeypatch):
    cat = _catalog_with_done_post(tmp_path, text="Old body", hash_value="old-hash")
    monkeypatch.setattr(
        ingest,
        "extract_from_html",
        lambda _html, _url: SimpleNamespace(
            body_html="Body",
            has_heavy_images=False,
            published_at="2024-06-01T12:00:00.000Z",
            title="Test Post",
        ),
    )
    monkeypatch.setattr(ingest, "html_to_plain", lambda _html: "Body")
    monkeypatch.setattr(ingest, "clean_for_tts", lambda _text, **_kwargs: "New body")

    ok, err = ingest.ingest_posts(cat, FakeClient(), force_refresh=True)

    post = cat.get("test-post")
    assert (ok, err) == (1, 0)
    assert post.text == "New body"
    assert post.audio_status == "stale"


def test_ingest_refresh_preserves_done_audio_when_cleaned_text_is_unchanged(tmp_path, monkeypatch):
    text = "Same body"
    cat = _catalog_with_done_post(tmp_path, text=text, hash_value=content_hash(text))
    monkeypatch.setattr(
        ingest,
        "extract_from_html",
        lambda _html, _url: SimpleNamespace(
            body_html="Body",
            has_heavy_images=False,
            published_at="2024-06-01T12:00:00.000Z",
            title="Test Post",
        ),
    )
    monkeypatch.setattr(ingest, "html_to_plain", lambda _html: "Body")
    monkeypatch.setattr(ingest, "clean_for_tts", lambda _text, **_kwargs: text)

    ok, err = ingest.ingest_posts(cat, FakeClient(), force_refresh=True)

    post = cat.get("test-post")
    assert (ok, err) == (1, 0)
    assert post.text == text
    assert post.audio_status == "done"
