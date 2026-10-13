"""Paywalled (members-only) posts: detection, ingest state changes, and feed handling."""

import sqlite3
from email.utils import parsedate_to_datetime

import httpx

from kellblog_audio import ingest
from kellblog_audio.catalog import Catalog
from kellblog_audio.extract import extract_from_html
from kellblog_audio.podcast import build_feed

URL = "https://www.kellblog.com/test-post/"
SLUG = "test-post"

# Ghost puts the CTA inside the content section after the preview; the class name also
# appears in every page's CSS, which must not count as a paywall.
STYLE = "<style>.gh-post-upgrade-cta { color: red; }</style>"
CTA = """
<aside class="gh-post-upgrade-cta"><div class="gh-post-upgrade-cta-content">
<h2>This post is for paying subscribers only</h2>
<a class="gh-btn" data-portal="signup" href="#/portal/signup">Subscribe now</a>
<p><small>Already have an account? <a data-portal="signin" href="#/portal/signin">Sign in</a></small></p>
</div></aside>
"""


def page(body: str, *, cta: str = "") -> str:
    return f"""<html><head>{STYLE}
<meta property="og:title" content="Test Post - Kellblog">
<meta property="article:published_time" content="2026-08-04T12:00:00.000Z">
</head><body><main><article><h1>Test Post</h1>
<section class="gh-content"><p>{body}</p>{cta}</section></article></main></body></html>"""


PAID_HTML = page("Only the preview paragraph is visible here.", cta=CTA)
FREE_HTML = page("The whole article is visible here for everyone.")


class FakeClient:
    def __init__(self, html: str) -> None:
        self.html = html

    def get(self, url, **kwargs):
        request = httpx.Request("GET", url)
        if url == ingest.RSS_URL:
            return httpx.Response(200, text="<rss><channel /></rss>", request=request)
        return httpx.Response(200, text=self.html, request=request)


def new_catalog(tmp_path, *, lastmod="2026-08-04T12:00:00.000Z"):
    cat = Catalog(tmp_path / "test.sqlite")
    cat.init_schema()
    cat.upsert_sitemap_entry(SLUG, URL, lastmod)
    return cat


def run_ingest(cat, html):
    return ingest.ingest_posts(cat, FakeClient(html))


# --- detection -------------------------------------------------------------------


def test_extract_flags_paywall_and_strips_the_footer():
    extracted = extract_from_html(PAID_HTML, URL)
    assert extracted.paywalled is True
    assert "paying subscribers" not in extracted.body_html
    assert "Subscribe now" not in extracted.body_html
    assert "preview paragraph" in extracted.body_html


def test_extract_ignores_paywall_css_on_free_posts():
    extracted = extract_from_html(FREE_HTML, URL)
    assert extracted.paywalled is False
    assert "whole article" in extracted.body_html


def test_extract_falls_back_to_the_heading_text_if_markup_changes():
    html = page("Preview text.", cta="<h2>This post is for subscribers only</h2>")
    extracted = extract_from_html(html, URL)
    assert extracted.paywalled is True
    assert "subscribers only" not in extracted.body_html


def test_extract_keeps_a_free_post_that_mentions_paying_subscribers_in_prose():
    html = page("Dave wrote that this post is for paying subscribers only, sometimes.")
    assert extract_from_html(html, URL).paywalled is False


# --- ingest state changes ----------------------------------------------------------


def test_new_paywalled_post_is_held_out_of_synthesis(tmp_path):
    cat = new_catalog(tmp_path)
    assert run_ingest(cat, PAID_HTML) == (1, 0)
    post = cat.get(SLUG)
    assert post.paywalled == 1
    assert post.audio_status == "paywalled"
    assert "paying subscribers" not in post.text
    assert post.released_at is None
    assert cat.list_by_filter(audio_status="pending") == []
    assert cat.counts()["audio_paywalled"] == 1


def test_published_episode_is_pulled_when_the_post_turns_out_paywalled(tmp_path):
    cat = new_catalog(tmp_path)
    cat.update_post(
        SLUG,
        title="Test Post",
        published_at="2026-08-04T12:00:00.000Z",
        year=2026,
        content_hash="old",
        ingest_status="done",
        audio_status="done",
        audio_path="output/audio/2026/test-post.mp3",
        audio_bytes=1234,
        duration_sec=60,
        feed_published_at="2026-08-05T00:00:00+00:00",
    )
    cat.update_post(SLUG, ingest_status="pending")
    run_ingest(cat, PAID_HTML)
    post = cat.get(SLUG)
    assert post.audio_status == "paywalled"
    assert post.audio_path is None
    assert post.audio_bytes is None
    assert post.feed_published_at is None


def test_flip_to_free_queues_narration_and_records_release_date(tmp_path):
    cat = new_catalog(tmp_path)
    run_ingest(cat, PAID_HTML)

    # Dave flips the post: the sitemap lastmod moves, which re-queues the ingest.
    cat.upsert_sitemap_entry(SLUG, URL, "2026-09-16T14:34:11.000Z")
    assert cat.get(SLUG).ingest_status == "pending"
    run_ingest(cat, FREE_HTML)

    post = cat.get(SLUG)
    assert post.paywalled == 0
    assert post.audio_status == "pending"
    assert post.released_at == "2026-09-16T14:34:11.000Z"
    assert "whole article" in post.text


def test_flip_to_free_regenerates_audio_made_from_the_preview(tmp_path):
    cat = new_catalog(tmp_path)
    run_ingest(cat, PAID_HTML)
    # Legacy state: episode was narrated from the preview and published as "done".
    cat.update_post(
        SLUG,
        audio_status="done",
        audio_path="output/audio/2026/test-post.mp3",
        duration_sec=60,
    )
    cat.upsert_sitemap_entry(SLUG, URL, "2026-10-01T15:19:31.000Z")
    run_ingest(cat, FREE_HTML)

    post = cat.get(SLUG)
    assert post.audio_status == "stale"
    assert post.audio_path is None
    assert post.released_at == "2026-10-01T15:19:31.000Z"


def test_still_paywalled_recheck_keeps_the_post_held(tmp_path):
    cat = new_catalog(tmp_path)
    run_ingest(cat, PAID_HTML)
    assert cat.queue_paywall_rechecks() == 1
    run_ingest(cat, PAID_HTML)
    post = cat.get(SLUG)
    assert post.audio_status == "paywalled"
    assert post.released_at is None


def test_free_post_is_not_rechecked_nightly(tmp_path):
    cat = new_catalog(tmp_path)
    run_ingest(cat, FREE_HTML)
    assert cat.queue_paywall_rechecks() == 0


# --- sitemap-driven re-ingest -------------------------------------------------------


def test_changed_sitemap_lastmod_requeues_a_done_post(tmp_path):
    cat = new_catalog(tmp_path)
    run_ingest(cat, FREE_HTML)
    assert cat.get(SLUG).ingest_status == "done"

    cat.upsert_sitemap_entry(SLUG, URL, "2026-08-04T12:00:00.000Z")  # unchanged
    assert cat.get(SLUG).ingest_status == "done"

    cat.upsert_sitemap_entry(SLUG, URL, "2026-09-01T00:00:00.000Z")  # edited
    assert cat.get(SLUG).ingest_status == "pending"


def test_an_edit_with_identical_text_keeps_the_existing_audio(tmp_path):
    cat = new_catalog(tmp_path)
    run_ingest(cat, FREE_HTML)
    cat.update_post(SLUG, audio_status="done", audio_path="output/audio/2026/test-post.mp3")
    cat.upsert_sitemap_entry(SLUG, URL, "2026-09-01T00:00:00.000Z")
    run_ingest(cat, FREE_HTML)
    assert cat.get(SLUG).audio_status == "done"


# --- migration of catalogs created before this change -------------------------------


def test_migration_flags_legacy_paywall_footers_and_trusts_the_rest(tmp_path):
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE posts (slug TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT,
            published_at TEXT, year INTEGER, rss_excerpt TEXT, categories TEXT, body_raw TEXT,
            text TEXT, word_count INTEGER, content_hash TEXT, sitemap_lastmod TEXT,
            etag TEXT, last_modified TEXT, ingest_status TEXT DEFAULT 'pending',
            ingest_error TEXT, audio_path TEXT, audio_bytes INTEGER, audio_etag TEXT,
            audio_status TEXT DEFAULT 'pending', audio_error TEXT, duration_sec INTEGER,
            episode_in_season INTEGER, feed_published_at TEXT, skip_reason TEXT,
            backfill_run_id TEXT);
        INSERT INTO posts (slug, url, text, sitemap_lastmod, ingest_status, audio_status)
        VALUES ('normal', 'u1', 'A normal post.', '2020-01-01', 'done', 'done'),
               ('legacy', 'u2', 'Preview.\n\nThis post is for paying subscribers only\n\nSubscribe now',
                '2026-10-01', 'done', 'done');
        """
    )
    conn.commit()
    conn.close()

    cat = Catalog(path)
    cat.init_schema()
    normal, legacy = cat.get("normal"), cat.get("legacy")
    assert normal.ingested_lastmod == "2020-01-01" and not normal.paywalled
    assert legacy.paywalled == 1 and legacy.ingested_lastmod is None

    # The next sitemap sync re-fetches only the legacy post.
    cat.upsert_sitemap_entry("normal", "u1", "2020-01-01")
    cat.upsert_sitemap_entry("legacy", "u2", "2026-10-01")
    assert cat.get("normal").ingest_status == "done"
    assert cat.get("legacy").ingest_status == "pending"

    cat.init_schema()  # idempotent: must not redo the migration
    assert cat.get("legacy").ingest_status == "pending"


# --- feed ------------------------------------------------------------------------------


def _feed_ready(cat, slug, **fields):
    cat.upsert_sitemap_entry(slug, f"https://www.kellblog.com/{slug}/", None)
    cat.update_post(
        slug,
        title=slug,
        published_at="2026-08-04T12:00:00.000Z",
        year=2026,
        text="Body.",
        content_hash="h",
        ingest_status="done",
        duration_sec=60,
        audio_path=f"output/audio/2026/{slug}.mp3",
        **fields,
    )


def test_feed_excludes_paywalled_posts(tmp_path):
    cat = Catalog(tmp_path / "feed.sqlite")
    cat.init_schema()
    _feed_ready(cat, "free-one", audio_status="done")
    _feed_ready(cat, "held-back", audio_status="paywalled", paywalled=1)
    xml = build_feed(cat, local_audio=True)
    assert "free-one" in xml
    assert "held-back" not in xml


def test_feed_pubdate_is_the_release_date_for_flipped_posts(tmp_path):
    cat = Catalog(tmp_path / "feed.sqlite")
    cat.init_schema()
    _feed_ready(cat, "flipped", audio_status="done", released_at="2026-10-01T15:19:31.000Z")
    _feed_ready(cat, "always-free", audio_status="done")
    xml = build_feed(cat, local_audio=True)

    items = {}
    for chunk in xml.split("<item>")[1:]:
        title = chunk.split("<title>")[1].split("</title>")[0]
        items[title] = parsedate_to_datetime(chunk.split("<pubDate>")[1].split("</pubDate>")[0])
    assert items["flipped"].isoformat().startswith("2026-10-01T15:19:31")
    assert items["always-free"].isoformat().startswith("2026-08-04T12:00:00")
    # Newest first: the just-released episode leads the feed.
    assert xml.index("flipped") < xml.index("always-free")
