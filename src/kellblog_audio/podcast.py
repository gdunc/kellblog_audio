"""Build iTunes-compliant podcast RSS feed."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from feedgen.feed import FeedGenerator

from kellblog_audio.catalog import Catalog, PostRow
from kellblog_audio.config import (
    FEED_URL,
    PUBLIC_BASE_URL,
    SHOW_AUTHOR,
    SHOW_CATEGORY,
    SHOW_CATEGORY_SUB,
    SHOW_EMAIL,
    SHOW_LANGUAGE,
    SHOW_SUBTITLE,
    SHOW_TITLE,
    get_settings,
)
from kellblog_audio.intro_outro import (
    SHOW_DESCRIPTION_HTML,
    build_episode_description_html,
    build_episode_description_plain,
)
from kellblog_audio.text_clean import excerpt_from_body, html_to_plain


def episode_guid(slug: str) -> str:
    return hashlib.sha256(f"kellblog-audio:{slug}".encode()).hexdigest()


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "00:00:00"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def enclosure_url(year: int, slug: str) -> str:
    return f"{PUBLIC_BASE_URL}/audio/{year}/{slug}.mp3"


def pub_date_rfc2822(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt)


def build_feed(catalog: Catalog, *, local_audio: bool = False) -> str:
    """Build RSS XML for all published episodes."""
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.title(SHOW_TITLE)
    fg.link(href=FEED_URL, rel="self")
    fg.link(href=PUBLIC_BASE_URL, rel="alternate")
    fg.description(SHOW_DESCRIPTION_HTML)
    fg.language(SHOW_LANGUAGE)
    fg.generator("kellblog-audio")
    fg.author({"name": SHOW_AUTHOR, "email": SHOW_EMAIL})

    fg.podcast.itunes_category(SHOW_CATEGORY, SHOW_CATEGORY_SUB)
    fg.podcast.itunes_summary(html_to_plain(SHOW_DESCRIPTION_HTML))
    fg.podcast.itunes_author(SHOW_AUTHOR)
    fg.podcast.itunes_owner(SHOW_AUTHOR, SHOW_EMAIL)
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_type("episodic")

    settings = get_settings()
    artwork = settings.root / "src" / "kellblog_audio" / "assets" / "show-artwork.png"
    if artwork.exists():
        fg.podcast.itunes_image(f"{PUBLIC_BASE_URL}/show-artwork.png")

    posts = catalog.list_by_filter()
    episodes = [
        p
        for p in posts
        if p.audio_status == "done"
        and p.published_at
        and p.title
    ]
    # Newest first in feed (podcast convention)
    episodes.sort(key=lambda p: p.published_at or "", reverse=True)

    for post in episodes:
        _add_episode(fg, post, catalog, local_audio=local_audio)

    return fg.rss_str(pretty=True).decode("utf-8")


def _add_episode(
    fg: FeedGenerator,
    post: PostRow,
    catalog: Catalog,
    *,
    local_audio: bool,
) -> None:
    fe = fg.add_entry()
    title = post.title or post.slug
    fe.title(title)
    fe.podcast.itunes_title(title)

    excerpt = post.rss_excerpt or excerpt_from_body(post.text or "")
    if post.rss_excerpt and "<" in post.rss_excerpt:
        excerpt_plain = html_to_plain(post.rss_excerpt)
    else:
        excerpt_plain = excerpt

    desc_html = build_episode_description_html(excerpt_plain, post.url)
    desc_plain = build_episode_description_plain(excerpt_plain, post.url)
    fe.description(desc_html)
    fe.content(desc_html)
    fe.podcast.itunes_summary(desc_plain)

    fe.guid(episode_guid(post.slug), permalink=False)
    fe.link(href=post.url)
    if post.published_at:
        fe.pubDate(pub_date_rfc2822(post.published_at))

    if post.year:
        fe.podcast.itunes_season(post.year)
    if post.episode_in_season:
        fe.podcast.itunes_episode(post.episode_in_season)
    fe.podcast.itunes_episode_type("full")

    year = post.year or 1970
    if local_audio and post.audio_path:
        audio_file = get_settings().root / post.audio_path
        if audio_file.exists():
            length = audio_file.stat().st_size
            fe.enclosure(str(audio_file.resolve()), length, "audio/mpeg")
    else:
        url = enclosure_url(year, post.slug)
        length = _remote_length(post)
        fe.enclosure(url, length, "audio/mpeg")

    fe.podcast.itunes_duration(format_duration(post.duration_sec))


def _remote_length(post: PostRow) -> int:
    if post.audio_path:
        local = get_settings().root / post.audio_path
        if local.exists():
            return local.stat().st_size
    return 0


def write_feed(catalog: Catalog, out_path: Path, *, local_audio: bool = False) -> Path:
    xml = build_feed(catalog, local_audio=local_audio)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(xml, encoding="utf-8")
    return out_path
