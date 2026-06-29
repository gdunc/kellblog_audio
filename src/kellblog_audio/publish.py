"""Publish audio and RSS to Cloudflare R2."""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import boto3
from botocore.config import Config

from kellblog_audio.catalog import Catalog
from kellblog_audio.config import (
    FEEDS_DIR,
    OUTPUT_DIR,
    PUBLIC_BASE_URL,
    R2_ACCESS_KEY_ID,
    R2_BUCKET,
    R2_ENDPOINT,
    R2_SECRET_ACCESS_KEY,
    get_settings,
)
from kellblog_audio.podcast import write_feed
from kellblog_audio.review_html import write_review_page


def _clean_etag(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip('"')


def get_s3_client():
    if not (R2_ENDPOINT and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY):
        raise RuntimeError(
            "R2 not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY, R2_BUCKET."
        )
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
    )


def upload_file(client, local: Path, key: str, content_type: str) -> str | None:
    client.upload_file(
        str(local),
        R2_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    try:
        resp = client.head_object(Bucket=R2_BUCKET, Key=key)
    except Exception:
        return None
    return _clean_etag(resp.get("ETag"))


def upload_bytes(client, payload: bytes, key: str, content_type: str) -> str | None:
    resp = client.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=payload,
        ContentType=content_type,
    )
    return _clean_etag(resp.get("ETag"))


def publish_local(catalog: Catalog, *, local_audio: bool = True) -> Path:
    """Write feed.xml locally without R2."""
    settings = get_settings()
    settings.ensure_dirs()
    catalog.assign_episode_numbers()
    feed_path = FEEDS_DIR / "feed.xml"
    write_feed(catalog, feed_path, local_audio=local_audio)
    (OUTPUT_DIR / "feed.xml").write_text(feed_path.read_text(encoding="utf-8"), encoding="utf-8")
    write_review_page(catalog)
    return feed_path


def publish_to_r2(catalog: Catalog, *, upload_audio: bool = True) -> str:
    client = get_s3_client()
    settings = get_settings()
    catalog.assign_episode_numbers()
    published_slugs: list[str] = []

    if upload_audio:
        posts = catalog.list_by_filter(audio_status="done")
        for post in posts:
            if not post.audio_path:
                continue
            local = settings.root / post.audio_path
            if not local.exists():
                continue
            year = post.year or 1970
            key = f"audio/{year}/{post.slug}.mp3"
            upload_file(client, local, key, "audio/mpeg")
            published_slugs.append(post.slug)
    else:
        published_slugs = [post.slug for post in catalog.list_by_filter(audio_status="done")]

    # Show artwork
    artwork = Path(__file__).parent / "assets" / "show-artwork.png"
    if artwork.exists():
        upload_file(client, artwork, "show-artwork.png", "image/png")

    review_page = write_review_page(catalog)
    upload_file(client, review_page, "index.html", "text/html; charset=utf-8")
    client.delete_object(Bucket=R2_BUCKET, Key="feedback/index.html")

    # Atomic feed swap (public URLs for podcast clients)
    settings.ensure_dirs()
    feed_path = FEEDS_DIR / "feed.xml"
    write_feed(catalog, feed_path, local_audio=False)
    tmp_key = "feed.xml.tmp"
    upload_file(client, feed_path, tmp_key, "application/rss+xml")
    client.copy_object(
        Bucket=R2_BUCKET,
        CopySource={"Bucket": R2_BUCKET, "Key": tmp_key},
        Key="feed.xml",
        MetadataDirective="REPLACE",
        ContentType="application/rss+xml",
    )
    client.delete_object(Bucket=R2_BUCKET, Key=tmp_key)

    for slug in published_slugs:
        catalog.mark_feed_published(slug)

    return f"{PUBLIC_BASE_URL}/feed.xml"


def _latest_catalog_key(client) -> str | None:
    prefix = "backup/catalog-"
    resp = client.list_objects_v2(Bucket=R2_BUCKET, Prefix=prefix)
    contents = resp.get("Contents") or []
    if not contents:
        return None
    latest = sorted(contents, key=lambda x: x["Key"])[-1]
    return latest["Key"]


@contextmanager
def _snapshot_catalog(path: Path) -> Iterator[Path]:
    if not path.exists():
        raise FileNotFoundError(path)
    with tempfile.TemporaryDirectory() as snapshot_dir:
        snapshot_path = Path(snapshot_dir) / path.name
        with sqlite3.connect(path, timeout=30.0) as source:
            source.execute("PRAGMA busy_timeout=30000")
            with sqlite3.connect(snapshot_path) as target:
                source.backup(target)
        yield snapshot_path


def backup_catalog(catalog: Catalog, key: str | None = None) -> str:
    client = get_s3_client()
    resolved_key = key or f"backup/catalog-{datetime.now(timezone.utc):%Y-%m-%d}.sqlite"
    with _snapshot_catalog(catalog.path) as snapshot:
        client.upload_file(
            str(snapshot),
            R2_BUCKET,
            resolved_key,
            ExtraArgs={"ContentType": "application/x-sqlite3"},
        )
    return resolved_key


def _catalog_sidecar_paths(path: Path) -> tuple[Path, Path]:
    return (
        path.with_name(f"{path.name}-wal"),
        path.with_name(f"{path.name}-shm"),
    )


def restore_catalog(catalog: Catalog, key: str | None = None) -> bool:
    """Download latest backup catalog from R2 if exists."""
    client = get_s3_client()
    resolved_key = key or _latest_catalog_key(client)
    if not resolved_key:
        return False
    catalog.path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=catalog.path.parent,
            prefix=f"{catalog.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
        client.download_file(R2_BUCKET, resolved_key, str(tmp_path))
        tmp_path.replace(catalog.path)
        for sidecar in _catalog_sidecar_paths(catalog.path):
            sidecar.unlink(missing_ok=True)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise
    return True
