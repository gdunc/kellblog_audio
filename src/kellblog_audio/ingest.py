"""Sitemap sync, fetch, and extract into catalog."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Callable

import httpx

from kellblog_audio.catalog import Catalog
from kellblog_audio.config import (
    BLOG_BASE,
    INGEST_RATE_LIMIT,
    RSS_URL,
    SITEMAP_URL,
    SKIP_SLUGS,
    get_settings,
)
from kellblog_audio.extract import content_hash, extract_from_html, slug_from_url
from kellblog_audio.text_clean import clean_for_tts, excerpt_from_body, html_to_plain


def fetch_sitemap(client: httpx.Client) -> list[tuple[str, str, str | None]]:
    resp = client.get(SITEMAP_URL, timeout=60)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    entries: list[tuple[str, str, str | None]] = []
    for url_el in root.findall(".//sm:url", ns):
        loc = url_el.find("sm:loc", ns)
        if loc is None or not loc.text:
            continue
        url = loc.text.strip()
        if "/tag/" in url or url.rstrip("/") == BLOG_BASE.rstrip("/"):
            continue
        slug = slug_from_url(url)
        if not slug:
            continue
        lastmod_el = url_el.find("sm:lastmod", ns)
        lastmod = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else None
        entries.append((slug, url, lastmod))
    return entries


def fetch_rss_excerpts(client: httpx.Client) -> dict[str, tuple[str, str]]:
    """Map slug -> (excerpt_html, categories comma-separated). Only recent items in RSS."""
    resp = client.get(RSS_URL, timeout=60)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    ns = {
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    result: dict[str, tuple[str, str]] = {}
    for item in root.findall(".//item"):
        link_el = item.find("link")
        if link_el is None or not link_el.text:
            continue
        slug = slug_from_url(link_el.text.strip())
        desc_el = item.find("description")
        excerpt = desc_el.text if desc_el is not None and desc_el.text else ""
        cats = [
            c.text.strip()
            for c in item.findall("category")
            if c.text
        ]
        result[slug] = (excerpt, ",".join(cats))
    return result


def sync_sitemap(catalog: Catalog, client: httpx.Client) -> int:
    entries = fetch_sitemap(client)
    for slug, url, lastmod in entries:
        catalog.upsert_sitemap_entry(slug, url, lastmod)
    return len(entries)


def ingest_posts(
    catalog: Catalog,
    client: httpx.Client,
    *,
    slug: str | None = None,
    limit: int | None = None,
    force_refresh: bool = False,
    progress: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    settings = get_settings()
    rss_map = fetch_rss_excerpts(client)
    pending = (
        catalog.list_by_filter()
        if force_refresh
        else catalog.list_by_filter(ingest_status="pending")
    )
    if slug:
        pending = [p for p in pending if p.slug == slug]
    if limit:
        pending = pending[:limit]

    ok, err = 0, 0
    min_interval = 1.0 / INGEST_RATE_LIMIT
    last_request = 0.0

    for post in pending:
        is_skip = post.slug in settings.skip_slugs

        elapsed = time.monotonic() - last_request
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        headers: dict[str, str] = {}
        if post.etag and not force_refresh:
            headers["If-None-Match"] = post.etag
        if post.last_modified and not force_refresh:
            headers["If-Modified-Since"] = post.last_modified

        try:
            resp = client.get(post.url, headers=headers, timeout=60, follow_redirects=True)
            last_request = time.monotonic()
            if resp.status_code == 304:
                catalog.update_post(post.slug, ingest_status="done")
                ok += 1
                continue
            resp.raise_for_status()
            extracted = extract_from_html(resp.text, post.url)
            plain_body = html_to_plain(extracted.body_html)
            tts_text = clean_for_tts(
                plain_body,
                image_disclaimer=extracted.has_heavy_images,
            )
            h = content_hash(tts_text)
            year = datetime.fromisoformat(
                extracted.published_at.replace("Z", "+00:00")
            ).year
            rss_excerpt, categories = rss_map.get(post.slug, ("", ""))
            if not rss_excerpt:
                rss_excerpt = excerpt_from_body(plain_body)

            existing = catalog.get(post.slug)
            if is_skip:
                audio_status = "skip"
            else:
                audio_status = existing.audio_status if existing else "pending"
                if not audio_status or audio_status == "skip":
                    audio_status = "pending"
                if existing and existing.content_hash != h:
                    if existing.audio_status == "done":
                        audio_status = "stale"
                    elif existing.audio_status not in {"pending", "stale"}:
                        audio_status = "pending"

            etag = resp.headers.get("etag")
            lm = resp.headers.get("last-modified")

            catalog.update_post(
                post.slug,
                title=extracted.title,
                published_at=extracted.published_at,
                year=year,
                rss_excerpt=rss_excerpt,
                categories=categories or None,
                body_raw=extracted.body_html,
                text=tts_text if not is_skip else None,
                word_count=len(tts_text.split()) if not is_skip else 0,
                content_hash=h,
                etag=etag,
                last_modified=lm,
                ingest_status="done",
                ingest_error=None,
                audio_status=audio_status,
                skip_reason="configured skip slug (external audio)" if is_skip else None,
            )
            ok += 1
            if progress:
                progress(f"ingested {post.slug}")
        except Exception as e:
            catalog.update_post(
                post.slug,
                ingest_status="error",
                ingest_error=str(e)[:500],
            )
            err += 1
            if progress:
                progress(f"error {post.slug}: {e}")

    catalog.assign_episode_numbers()
    return ok, err


def ingest_all(
    catalog: Catalog | None = None,
    *,
    slug: str | None = None,
    limit: int | None = None,
    force_refresh: bool = False,
) -> Catalog:
    settings = get_settings()
    settings.ensure_dirs()
    if catalog is None:
        catalog = Catalog(settings.catalog_path)
    catalog.init_schema()
    with httpx.Client(headers={"User-Agent": "KellblogAudioBot/1.0 (+https://thisisgrant.com)"}) as client:
        n = sync_sitemap(catalog, client)
        print(f"Synced {n} URLs from sitemap")
        ok, err = ingest_posts(
            catalog,
            client,
            slug=slug,
            limit=limit,
            force_refresh=force_refresh,
            progress=print,
        )
        print(f"Ingest complete: {ok} ok, {err} errors")
    return catalog
