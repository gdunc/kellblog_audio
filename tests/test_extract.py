from pathlib import Path

from kellblog_audio.extract import content_hash, extract_from_html, slug_from_url
from kellblog_audio.text_clean import clean_for_tts, strip_site_suffix

FIXTURES = Path(__file__).parent / "fixtures"


def test_slug_from_url():
    assert slug_from_url("https://www.kellblog.com/foo-bar/") == "foo-bar"


def test_strip_site_suffix():
    assert strip_site_suffix("Hello | Kellblog") == "Hello"


def test_extract_short_post():
    html = (FIXTURES / "short_post.html").read_text()
    post = extract_from_html(html, "https://www.kellblog.com/taxonomies-and-tags/")
    assert post.title == "Taxonomies and Tags"
    assert "2010-03-15" in post.published_at
    assert "SaaS" in post.body_html


def test_clean_for_tts_glossary_and_footnotes():
    text = "We use SaaS and ARR.\n\n## Notes\n\n[1] A note."
    cleaned = clean_for_tts(text)
    assert "sass" in cleaned
    assert "A. R. R." in cleaned
    assert "Notes follow" in cleaned
    assert "[1]" not in cleaned.split("Notes follow")[0]


def test_content_hash_stable():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
