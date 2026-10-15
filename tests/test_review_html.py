import json
import tempfile
from pathlib import Path

from kellblog_audio.catalog import Catalog
from kellblog_audio.config import PUBLIC_BASE_URL
from kellblog_audio.review_html import concern_reasons, write_review_page


def _catalog_with_post(db: Path, slug: str, **fields):
    cat = Catalog(db)
    cat.init_schema()
    cat.upsert_sitemap_entry(slug, f"https://www.kellblog.com/{slug}/", None)
    cat.update_post(
        slug,
        title=fields.get("title", "Test Post"),
        published_at=fields.get("published_at", "2024-06-01T12:00:00.000Z"),
        year=fields.get("year", 2024),
        url=f"https://www.kellblog.com/{slug}/",
        text=fields.get("text", "Body text for TTS."),
        word_count=fields.get("word_count", 4),
        ingest_status="done",
        audio_status=fields.get("audio_status", "done"),
        duration_sec=fields.get("duration_sec", 120),
        audio_path=fields.get("audio_path", f"output/audio/2024/{slug}.mp3"),
    )
    return cat


def test_concern_reasons_flags_review_thresholds():
    reasons = concern_reasons(
        {
            "source_coverage": 0.91,
            "tail_similarity": 0.79,
            "body_wpm": 201,
            "max_repeated_three_gram": 7,
        }
    )

    assert "coverage 91.0%" in reasons
    assert "ending match 79.0%" in reasons
    assert "pace 201 WPM" in reasons
    assert "repeat x7" in reasons


def test_write_review_page_is_clean_listening_page():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cat = _catalog_with_post(tmp_path / "test.sqlite", "test-post")
        qa_dir = tmp_path / "qa"
        qa_dir.mkdir()
        (qa_dir / "test-post.qa.json").write_text(
            json.dumps(
                {
                    "passed": False,
                    "reason": "repetition 16 > 12",
                    "source_coverage": 0.91,
                    "tail_similarity": 0.9,
                    "body_wpm": 170,
                    "max_repeated_three_gram": 16,
                }
            ),
            encoding="utf-8",
        )
        out = tmp_path / "index.html"
        feedback = tmp_path / "feedback" / "index.html"
        feedback.parent.mkdir()
        feedback.write_text("stale redirect", encoding="utf-8")

        write_review_page(cat, out_path=out, qa_dir=qa_dir, updated_at="2026-06-08 10:00")

        html = out.read_text(encoding="utf-8")
        assert not feedback.exists()
        assert "<title>Kellblog Audio</title>" in html
        assert "1 episode" in html
        assert "/audio/2024/test-post.mp3" in html
        assert "Needs manual audit" not in html
        assert "What to review" not in html
        assert "QA passed" not in html
        assert "Whisper QA" not in html
        assert "Manual audit" not in html
        assert f"{PUBLIC_BASE_URL}/feed.xml" in html or "/feed.xml" in html
        assert "Subscribe via" in html
        assert "Feedback" not in html
        assert "repetition 16" not in html


def test_write_review_page_includes_share_controls():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cat = _catalog_with_post(
            tmp_path / "test.sqlite",
            "share-me",
            title="Share Me",
        )
        out = tmp_path / "index.html"

        write_review_page(cat, out_path=out, qa_dir=tmp_path / "qa", updated_at="2026-06-08 10:00")

        html = out.read_text(encoding="utf-8")
        assert 'data-copy-page-url="https://kellblog.thisisgrant.com/index.html"' in html
        assert "subject=Kellblog%20Audio" in html
        assert "body=Listen%20to%20the%20Kellblog%20audio%20archive%20here" in html
        assert (
            'data-copy-page-url="https://kellblog.thisisgrant.com/index.html#episode-share-me"'
            in html
        )
        assert 'data-share-label="Share Me"' in html
        assert "navigator.clipboard.writeText" in html
        assert "Copy link" in html
