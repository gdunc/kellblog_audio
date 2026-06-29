"""Maintenance helpers for resetting generated pipeline artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kellblog_audio.catalog import Catalog
from kellblog_audio.config import AUDIO_DIR, get_settings


@dataclass
class ResetAudioResult:
    reset_posts: int = 0
    deleted_files: int = 0
    missing_files: int = 0


def reset_generated_audio(
    catalog: Catalog,
    *,
    root: Path | None = None,
    delete_files: bool = True,
) -> ResetAudioResult:
    """Reset all generated-audio posts to pending, preserving external-audio skips."""
    settings = get_settings()
    base = root or settings.root
    result = ResetAudioResult()

    for post in catalog.list_by_filter():
        if post.audio_status == "skip":
            continue
        if delete_files and post.audio_path:
            audio_file = base / post.audio_path
            if audio_file.exists():
                audio_file.unlink()
                result.deleted_files += 1
            else:
                result.missing_files += 1
        catalog.update_post(
            post.slug,
            audio_path=None,
            audio_bytes=None,
            audio_etag=None,
            audio_status="pending",
            audio_error=None,
            duration_sec=None,
            feed_published_at=None,
            backfill_run_id=None,
        )
        result.reset_posts += 1

    if delete_files and root is None and AUDIO_DIR.exists():
        for mp3 in AUDIO_DIR.rglob("*.mp3"):
            mp3.unlink()
            result.deleted_files += 1
    return result
