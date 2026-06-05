"""Synthesize episodes from catalog text."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Callable

from kellblog_audio.catalog import Catalog
from kellblog_audio.config import AUDIO_DIR, get_settings
from kellblog_audio.intro_outro import SPOKEN_OUTRO, spoken_intro
from kellblog_audio.tts import (
    TTSProvider,
    get_provider,
    merge_audio_parts,
    synthesize_text_to_wav,
    wav_to_mp3,
)


def audio_output_path(year: int, slug: str) -> Path:
    return AUDIO_DIR / str(year) / f"{slug}.mp3"


def shard_index_for(slug: str, shard_count: int) -> int:
    """Stable shard assignment for a slug (independent of process/list ordering)."""
    digest = hashlib.md5(slug.encode("utf-8")).hexdigest()
    return int(digest, 16) % shard_count


def synthesize_post(
    catalog: Catalog,
    slug: str,
    provider_name: str | None = None,
    *,
    force: bool = False,
    provider: TTSProvider | None = None,
) -> Path | None:
    post = catalog.get(slug)
    if not post or not post.text:
        raise ValueError(f"Post {slug} not ingested or has no text")
    if post.audio_status == "skip":
        return None
    out_path = audio_output_path(post.year or 1970, slug)
    if out_path.exists() and post.audio_status == "done" and not force:
        return out_path

    if provider is None:
        provider = get_provider(provider_name)
    intro = spoken_intro(post.title or slug, post.published_at or "1970-01-01T00:00:00Z")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        intro_wav = tmp_path / "intro.wav"
        body_wav = tmp_path / "body.wav"
        outro_wav = tmp_path / "outro.wav"

        synthesize_text_to_wav(provider, intro, intro_wav)
        synthesize_text_to_wav(provider, post.text, body_wav)
        synthesize_text_to_wav(provider, SPOKEN_OUTRO, outro_wav)

        duration = merge_audio_parts(
            [intro_wav, body_wav, outro_wav],
            out_path,
            title=post.title or slug,
            track=post.episode_in_season,
        )

    catalog.update_post(
        slug,
        audio_path=str(out_path.relative_to(get_settings().root)),
        audio_status="done",
        audio_error=None,
        duration_sec=duration,
    )
    return out_path


def synthesize_batch(
    catalog: Catalog,
    *,
    pending_only: bool = True,
    year: int | None = None,
    slug: str | None = None,
    force: bool = False,
    provider_name: str | None = None,
    limit: int | None = None,
    shard_index: int | None = None,
    shard_count: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    settings = get_settings()
    settings.ensure_dirs()

    if pending_only:
        posts = catalog.list_by_filter(audio_status="pending")
        posts += catalog.list_by_filter(audio_status="stale")
    else:
        posts = catalog.list_by_filter()
        posts = [p for p in posts if p.audio_status not in ("skip",) and p.text]

    if year is not None:
        posts = [p for p in posts if p.year == year]
    if slug:
        posts = [p for p in posts if p.slug == slug]
    if shard_count and shard_count > 1:
        idx = shard_index or 0
        posts = [p for p in posts if shard_index_for(p.slug, shard_count) == idx]
    if limit:
        posts = posts[:limit]

    # Build the model once and reuse it for the whole batch.
    provider = get_provider(provider_name)

    ok, err = 0, 0
    for post in posts:
        try:
            synthesize_post(
                catalog, post.slug, provider_name, force=force, provider=provider
            )
            ok += 1
            if progress:
                progress(f"synthesized {post.slug}")
        except Exception as e:
            catalog.update_post(post.slug, audio_status="error", audio_error=str(e)[:500])
            err += 1
            if progress:
                progress(f"error {post.slug}: {e}")
    return ok, err
