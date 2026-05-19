"""Publish audio and RSS to Cloudflare R2."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

from kellblog_audio.catalog import Catalog
from kellblog_audio.config import (
    FEEDS_DIR,
    PUBLIC_BASE_URL,
    R2_ACCESS_KEY_ID,
    R2_BUCKET,
    R2_ENDPOINT,
    R2_SECRET_ACCESS_KEY,
    get_settings,
)
from kellblog_audio.podcast import write_feed


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


def upload_file(client, local: Path, key: str, content_type: str) -> None:
    client.upload_file(
        str(local),
        R2_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def publish_local(catalog: Catalog) -> Path:
    """Write feed.xml locally without R2."""
    settings = get_settings()
    settings.ensure_dirs()
    feed_path = FEEDS_DIR / "feed.xml"
    write_feed(catalog, feed_path)
    return feed_path


def publish_to_r2(catalog: Catalog, *, upload_audio: bool = True) -> str:
    client = get_s3_client()
    settings = get_settings()

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
            catalog.mark_feed_published(post.slug)

    # Show artwork
    artwork = Path(__file__).parent / "assets" / "show-artwork.png"
    if artwork.exists():
        upload_file(client, artwork, "show-artwork.png", "image/png")

    # Atomic feed swap
    feed_path = publish_local(catalog)
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

    return f"{PUBLIC_BASE_URL}/feed.xml"


def backup_catalog(catalog: Catalog) -> str:
    client = get_s3_client()
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"backup/catalog-{date}.sqlite"
    client.upload_file(
        str(catalog.path),
        R2_BUCKET,
        key,
        ExtraArgs={"ContentType": "application/x-sqlite3"},
    )
    return key


def restore_catalog(catalog: Catalog) -> bool:
    """Download latest backup catalog from R2 if exists."""
    client = get_s3_client()
    prefix = "backup/catalog-"
    resp = client.list_objects_v2(Bucket=R2_BUCKET, Prefix=prefix)
    contents = resp.get("Contents") or []
    if not contents:
        return False
    latest = sorted(contents, key=lambda x: x["Key"])[-1]
    catalog.path.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(R2_BUCKET, latest["Key"], str(catalog.path))
    return True
