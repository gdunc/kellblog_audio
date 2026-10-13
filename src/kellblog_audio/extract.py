"""Extract post metadata and body from Kellblog HTML."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from kellblog_audio.text_clean import strip_site_suffix


@dataclass
class ExtractedPost:
    title: str
    published_at: str
    body_html: str
    has_heavy_images: bool
    paywalled: bool = False


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1] if path else ""


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def extract_from_html(html: str, url: str) -> ExtractedPost:
    soup = BeautifulSoup(html, "lxml")
    title = _extract_title(soup)
    published_at = _extract_published_at(soup)
    body_html, has_images, paywalled = _extract_body(soup)
    return ExtractedPost(
        title=title,
        published_at=published_at,
        body_html=body_html,
        has_heavy_images=has_images,
        paywalled=paywalled,
    )


def _extract_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return strip_site_suffix(og["content"])
    if soup.title and soup.title.string:
        return strip_site_suffix(soup.title.string)
    h1 = soup.find("h1")
    return strip_site_suffix(h1.get_text(strip=True)) if h1 else "Untitled"


def _extract_published_at(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", property="article:published_time")
    if meta and meta.get("content"):
        return meta["content"]
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict) and data.get("datePublished"):
                return data["datePublished"]
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("datePublished"):
                        return item["datePublished"]
        except (json.JSONDecodeError, TypeError):
            continue
    time_tag = soup.find("time", datetime=True)
    if time_tag and time_tag.get("datetime"):
        return time_tag["datetime"]
    return "1970-01-01T00:00:00.000Z"


# Ghost renders this block after the preview of members-only / paid posts. The class
# name also appears in every page's CSS, so match the element, not the string.
PAYWALL_CTA_SELECTOR = "aside.gh-post-upgrade-cta"
PAYWALL_LINE = re.compile(r"^\s*This post is for (paying )?subscribers only\s*$", re.I | re.M)


def _strip_paywall(target) -> bool:
    """Remove the subscribe call-to-action from `target`; True if the post is paywalled."""
    paywalled = False
    for el in target.select(PAYWALL_CTA_SELECTOR):
        el.decompose()
        paywalled = True
    # Fallback if the theme changes the markup: the heading text alone is enough.
    for heading in target.find_all(["h1", "h2", "h3", "h4", "p"]):
        if PAYWALL_LINE.match(heading.get_text()):
            heading.decompose()
            paywalled = True
    return paywalled


def _extract_body(soup: BeautifulSoup) -> tuple[str, bool, bool]:
    article = soup.find("article")
    if article:
        content = article.find(class_=re.compile(r"gh-content|post-content|article-body"))
        target = content or article
    else:
        target = soup.find(class_=re.compile(r"gh-content|post-content")) or soup.body
    if not target:
        target = soup
    paywalled = _strip_paywall(target)
    imgs = len(target.find_all("img"))
    # Remove read-more / footer cruft
    for sel in [".read-more", ".kg-card-teaser", "footer"]:
        for el in target.select(sel):
            el.decompose()
    return str(target), imgs > 3, paywalled
