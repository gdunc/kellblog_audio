import json
import tempfile
from pathlib import Path

from kellblog_audio.catalog import Catalog
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


def test_write_review_page_removes_feedback_and_lists_concerns():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cat = _catalog_with_post(tmp_path / "test.sqlite", "test-post")
        qa_dir = tmp_path / "qa"
        qa_dir.mkdir()
        (qa_dir / "test-post.qa.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "source_coverage": 0.91,
                    "tail_similarity": 0.9,
                    "body_wpm": 170,
                    "max_repeated_three_gram": 2,
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
        assert "1 published MP3 available for review" in html
        assert "Feedback" not in html
        assert "Needs manual audit" in html
        assert "coverage 91.0%" in html
        assert "What to review" in html
        assert "/audio/2024/test-post.mp3" in html
