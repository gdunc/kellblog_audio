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
        audio_path=f"output/audio/{year}/{slug}.mp3",
        **{"duration_sec": 125, **fields},
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
    assert "Read original" in page and "Download MP3" not in page
    assert 'id="episode-search"' in page


def test_page_uses_release_date_for_flipped_posts(tmp_path):
    cat = Catalog(tmp_path / "c.sqlite")
    cat.init_schema()
    _add(cat, "flipped", "Flipped", "2025-06-01T00:00:00.000Z", 2025, released_at="2026-10-01T15:19:31.000Z")
    page = write_review_page(cat, out_path=tmp_path / "index.html", qa_dir=tmp_path / "qa").read_text(encoding="utf-8")
    assert "2026-10-01" in page


def test_subscribe_buttons_pending_until_ids_set_then_link():
    from kellblog_audio.listen_platforms import listen_platforms
    from kellblog_audio.review_html import _render_subscribe

    pending = _render_subscribe(listen_platforms(apple_id="", spotify_id=""))
    assert pending.count('class="listen-btn is-pending"') == 6
    assert "Apple Podcasts" in pending and "Pocket Casts" in pending
    assert "<a " not in pending  # nothing clickable that goes nowhere
    assert 'data-copy-page-url="https://kellblog.thisisgrant.com/feed.xml"' in pending

    live = _render_subscribe(
        listen_platforms(
            apple_id="123",
            spotify_id="abc",
            amazon_url="https://music.amazon.com/podcasts/xyz",
            iheart_url="https://www.iheart.com/podcast/kellblog/",
        )
    )
    assert "is-pending" not in live
    assert live.count('target="_blank" rel="noopener"') == 6
    assert 'href="https://music.amazon.com/podcasts/xyz"' in live
    assert 'href="https://www.iheart.com/podcast/kellblog/"' in live
    assert 'href="https://podcasts.apple.com/podcast/id123"' in live
    assert 'href="https://open.spotify.com/show/abc"' in live
    assert 'href="https://overcast.fm/itunes123"' in live
    assert 'href="https://pca.st/itunes/123"' in live


def test_page_header_advertises_feed_for_autodiscovery(tmp_path):
    cat = Catalog(tmp_path / "c.sqlite")
    cat.init_schema()
    _add(cat, "a", "A", "2026-01-05T00:00:00.000Z", 2026)
    page = write_review_page(cat, out_path=tmp_path / "index.html", qa_dir=tmp_path / "qa").read_text(encoding="utf-8")
    assert 'rel="alternate" type="application/rss+xml"' in page


def test_platform_env_vars_feed_default_links(monkeypatch):
    import importlib

    import kellblog_audio.listen_platforms as lp

    monkeypatch.setenv("KELLBLOG_APPLE_PODCASTS_ID", " 999 ")
    monkeypatch.setenv("KELLBLOG_IHEART_URL", "https://www.iheart.com/podcast/k/")
    try:
        links = {p.key: p.url for p in importlib.reload(lp).listen_platforms()}
        assert links["apple"] == "https://podcasts.apple.com/podcast/id999"
        assert links["overcast"] == "https://overcast.fm/itunes999"
        assert links["iheart"] == "https://www.iheart.com/podcast/k/"
        assert links["spotify"] == "" and links["amazon"] == ""
    finally:
        monkeypatch.undo()
        importlib.reload(lp)


def test_copy_feedback_keeps_button_icons():
    from kellblog_audio.review_html import _share_script

    script = _share_script()
    assert 'button.querySelector(".label")' in script


def test_page_handles_missing_audio_date_duration_and_long_summary(tmp_path):
    cat = Catalog(tmp_path / "c.sqlite")
    cat.init_schema()
    _add(cat, "no-audio", "No Audio", "2026-01-05T00:00:00.000Z", 2026)
    cat.update_post("no-audio", audio_path=None)
    _add(cat, "bare", "Bare", None, None, duration_sec=None, rss_excerpt="word " * 80)
    page = write_review_page(cat, out_path=tmp_path / "index.html", qa_dir=tmp_path / "qa").read_text(encoding="utf-8")

    assert "No Audio" not in page  # nothing to play → not listed
    assert 'id="year-0"' in page and "Undated" in page
    assert "…" in page  # long summary truncated on a word boundary
    assert '<div class="meta"></div>' in page  # no date, no duration


def test_public_audio_path_normalises():
    from kellblog_audio.review_html import _public_audio_path

    assert _public_audio_path(None) == ""
    assert _public_audio_path("output\\audio\\2026\\a.mp3") == "/audio/2026/a.mp3"
    assert _public_audio_path("/audio/a.mp3") == "/audio/a.mp3"
