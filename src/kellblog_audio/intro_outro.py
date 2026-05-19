"""Intro/outro spoken lines and RSS attribution footer."""

from __future__ import annotations

from datetime import datetime

from kellblog_audio.config import SHOW_SUBTITLE

# Spoken outro (audio)
SPOKEN_OUTRO = (
    "This audio version was created by Grant Duncan and AI, with permission from Dave."
)

# RSS / show notes footer (HTML)
ATTRIBUTION_HTML = (
    "<p>This audio version was created by Grant Duncan and AI, "
    "with permission from Dave. Grant can be found at "
    '<a href="https://thisisgrant.com">thisisgrant.com</a>.</p>'
)

ATTRIBUTION_PLAIN = (
    "This audio version was created by Grant Duncan and AI, "
    "with permission from Dave. Grant can be found at thisisgrant.com."
)

SHOW_DESCRIPTION_HTML = f"""<p>{SHOW_SUBTITLE}</p>
<p>AI-narrated audio editions of posts from <a href="https://www.kellblog.com">Kellblog</a>.</p>
{ATTRIBUTION_HTML}"""


def format_long_date(iso_date: str) -> str:
    """e.g. 2024-11-05T... -> November 5, 2024"""
    dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def spoken_intro(title: str, published_at: str) -> str:
    long_date = format_long_date(published_at)
    return f"This is a Kellblog post from {long_date}, titled {title}."


def build_episode_description_html(
    author_excerpt: str,
    post_url: str,
) -> str:
    excerpt = author_excerpt.strip()
    if excerpt and not excerpt.startswith("<"):
        excerpt = f"<p>{_escape_html(excerpt)}</p>"
    elif excerpt and not excerpt.startswith("<p"):
        excerpt = f"<p>{excerpt}</p>"

    parts = [
        excerpt,
        f'<p>Read the original post on Kellblog: <a href="{post_url}">{post_url}</a></p>',
        ATTRIBUTION_HTML,
    ]
    return "\n".join(p for p in parts if p)


def build_episode_description_plain(author_excerpt: str, post_url: str) -> str:
    parts = [
        author_excerpt.strip(),
        f"Read the original post on Kellblog: {post_url}",
        ATTRIBUTION_PLAIN,
    ]
    return "\n\n".join(p for p in parts if p)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
