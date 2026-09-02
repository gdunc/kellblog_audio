"""Publish audio and RSS to Cloudflare R2."""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
import tempfile
import zipfile
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
    QA_TRANSCRIPTS_DIR,
    R2_ACCESS_KEY_ID,
    R2_BUCKET,
    R2_ENDPOINT,
    R2_SECRET_ACCESS_KEY,
    get_settings,
)
from kellblog_audio.catalog import stamp_missing_audio_bytes
from kellblog_audio.podcast import write_feed
from kellblog_audio.qa import qa_report_passed, read_qa_report
from kellblog_audio.review_html import write_review_page

MIN_QA_PASS_FRACTION = 0.5
MIN_QA_PASS_ARCHIVE = 50


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
    stamp_missing_audio_bytes(catalog, root=settings.root)
    catalog.assign_episode_numbers()
    feed_path = FEEDS_DIR / "feed.xml"
    write_feed(catalog, feed_path, local_audio=local_audio, require_qa=True)
    (OUTPUT_DIR / "feed.xml").write_text(feed_path.read_text(encoding="utf-8"), encoding="utf-8")
    write_review_page(catalog, require_qa=True)
    return feed_path


def _upload_done_audio(catalog: Catalog, client, *, settings) -> list[str]:
    published_slugs: list[str] = []
    for post in catalog.list_by_filter(audio_status="done"):
        if not post.audio_path:
            continue
        local = settings.root / post.audio_path
        if not local.exists():
            continue
        year = post.year or 1970
        key = f"audio/{year}/{post.slug}.mp3"
        upload_file(client, local, key, "audio/mpeg")
        published_slugs.append(post.slug)
    return published_slugs


def _upload_site_assets(catalog: Catalog, client, *, require_qa: bool) -> Path:
    artwork = Path(__file__).parent / "assets" / "show-artwork.png"
    if artwork.exists():
        upload_file(client, artwork, "show-artwork.png", "image/png")

    review_page = write_review_page(catalog, require_qa=require_qa)
    upload_file(client, review_page, "index.html", "text/html; charset=utf-8")
    client.delete_object(Bucket=R2_BUCKET, Key="feedback/index.html")
    return review_page


def publish_site_to_r2(catalog: Catalog, *, upload_audio: bool = True) -> str:
    """Upload listening page (+ optional MP3s) without updating the podcast feed."""
    client = get_s3_client()
    settings = get_settings()
    settings.ensure_dirs()

    if upload_audio:
        _upload_done_audio(catalog, client, settings=settings)

    _upload_site_assets(catalog, client, require_qa=False)
    return f"{PUBLIC_BASE_URL}/index.html"


def _feed_slugs(done_posts) -> list[str]:
    slugs: list[str] = []
    for post in done_posts:
        report = read_qa_report(post.slug, output_dir=QA_TRANSCRIPTS_DIR)
        if report is None or report.get("passed") is True:
            slugs.append(post.slug)
    return slugs


def publish_to_r2(catalog: Catalog, *, upload_audio: bool = True) -> str:
    client = get_s3_client()
    settings = get_settings()
    stamp_missing_audio_bytes(catalog, root=settings.root)
    catalog.assign_episode_numbers()
    done_posts = catalog.list_by_filter(audio_status="done")
    passed_count = sum(1 for post in done_posts if qa_report_passed(post.slug))
    if len(done_posts) >= MIN_QA_PASS_ARCHIVE and passed_count < MIN_QA_PASS_FRACTION * len(
        done_posts
    ):
        raise RuntimeError(
            "QA restore looks empty: "
            f"{passed_count}/{len(done_posts)} done episode(s) have passing QA"
        )

    if upload_audio:
        published_slugs = _upload_done_audio(catalog, client, settings=settings)
    else:
        published_slugs = _feed_slugs(done_posts)

    _upload_site_assets(catalog, client, require_qa=True)

    # Atomic feed swap (public URLs for podcast clients)
    settings.ensure_dirs()
    feed_path = FEEDS_DIR / "feed.xml"
    write_feed(catalog, feed_path, local_audio=False, require_qa=True)
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


def _latest_qa_key(client) -> str | None:
    prefix = "backup/qa-reports-"
    resp = client.list_objects_v2(Bucket=R2_BUCKET, Prefix=prefix)
    contents = resp.get("Contents") or []
    if not contents:
        return None
    latest = sorted(contents, key=lambda x: x["Key"])[-1]
    return latest["Key"]


def backup_qa_reports(key: str | None = None) -> str:
    client = get_s3_client()
    resolved_key = key or f"backup/qa-reports-{datetime.now(timezone.utc):%Y-%m-%d}.zip"
    QA_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "qa-reports.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(QA_TRANSCRIPTS_DIR.glob("*.qa.json")):
                zf.write(path, arcname=path.name)
        client.upload_file(
            str(archive),
            R2_BUCKET,
            resolved_key,
            ExtraArgs={"ContentType": "application/zip"},
        )
    return resolved_key


def restore_qa_reports(key: str | None = None) -> bool:
    client = get_s3_client()
    resolved_key = key or _latest_qa_key(client)
    if not resolved_key:
        return False
    QA_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "qa-reports.zip"
        client.download_file(R2_BUCKET, resolved_key, str(archive))
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                name = Path(info.filename).name
                if not name.endswith(".qa.json"):
                    continue
                target = QA_TRANSCRIPTS_DIR / name
                target.write_bytes(zf.read(info))
    return True


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
