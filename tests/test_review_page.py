"""Public listening page: year grouping, ordering, summaries, labels."""

from kellblog_audio.catalog import Catalog
from kellblog_audio.review_html import write_review_page


def _add(cat, slug, title, published, year, **fields):
    cat.upsert_sitemap_entry(slug, f"https://www.kellblog.com/{slug}/", None)
    cat.update_post(
        slug,
        title=title,
        published_at=published,
        year=year,
        text="Body.",
        content_hash="h",
        ingest_status="done",
        audio_status="done",
        duration_sec=125,
        audio_path=f"output/audio/{year}/{slug}.mp3",
        **fields,
    )


def test_page_groups_by_year_newest_first_with_summaries_and_clear_labels(tmp_path):
    cat = Catalog(tmp_path / "c.sqlite")
    cat.init_schema()
    _add(cat, "old-post", "Old Post", "2019-03-01T00:00:00.000Z", 2019, rss_excerpt="An old summary.")
    _add(cat, "new-a", "New A", "2026-01-05T00:00:00.000Z", 2026, rss_excerpt="<p>First <b>new</b> summary.</p>")
    _add(cat, "new-b", "New B", "2026-02-05T00:00:00.000Z", 2026)

    out = write_review_page(cat, out_path=tmp_path / "index.html", qa_dir=tmp_path / "qa")
    page = out.read_text(encoding="utf-8")

    # Years newest first, episodes newest first within a year.
    assert page.index('id="year-2026"') < page.index('id="year-2019"')
    assert page.index("New B") < page.index("New A") < page.index("Old Post")
    assert 'href="#year-2026"' in page and 'href="#year-2019"' in page

    # Summaries are plain text (HTML stripped), and the buttons say what they do.
    assert "An old summary." in page
    assert "First new summary." in page and "<b>new</b>" not in page
    assert "Read original" in page and "Download MP3" in page
    assert 'id="episode-search"' in page


def test_page_uses_release_date_for_flipped_posts(tmp_path):
    cat = Catalog(tmp_path / "c.sqlite")
    cat.init_schema()
    _add(cat, "flipped", "Flipped", "2025-06-01T00:00:00.000Z", 2025, released_at="2026-10-01T15:19:31.000Z")
    page = write_review_page(cat, out_path=tmp_path / "index.html", qa_dir=tmp_path / "qa").read_text(encoding="utf-8")
    assert "2026-10-01" in page
