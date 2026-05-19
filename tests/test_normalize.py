from kellblog_audio.glossary import apply_glossary
from kellblog_audio.text_clean import excerpt_from_body, normalize_unicode


def test_glossary_saas():
    assert "sass" in apply_glossary("Our SaaS product")


def test_normalize_smart_quotes():
    assert '"' in normalize_unicode("\u201chello\u201d")


def test_excerpt_truncates():
    long = "Word. " * 200
    ex = excerpt_from_body(long, max_chars=100)
    assert len(ex) <= 105
    assert ex.endswith("…") or len(ex) <= 100
