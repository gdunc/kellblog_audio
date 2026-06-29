"""Synthesize episodes from catalog text."""

from __future__ import annotations

import hashlib
import resource
import shutil
import signal
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Graceful-shutdown support
#
# When the OS delivers SIGTERM (e.g. macOS memory-pressure kill, `kill <pid>`,
# or launchd stopping the process) we set this event.  synthesize_batch checks
# the flag between episodes so the in-progress chunk can finish and the catalog
# entry can be committed before we exit – avoiding a partial-write.
#
# SIGKILL (kill -9) cannot be caught; in that case Chatterbox's multiprocessing
# semaphores leak (harmless warning from resource_tracker at shutdown).
# ---------------------------------------------------------------------------
_stop_requested = threading.Event()


def _handle_stop_signal(signum: int, _frame: object) -> None:
    _stop_requested.set()


signal.signal(signal.SIGTERM, _handle_stop_signal)

from kellblog_audio.catalog import Catalog
from kellblog_audio.config import AUDIO_DIR, DATA_DIR, MAX_AUDIO_BODY_WPM, get_settings
from kellblog_audio.distributed_backfill import ShardManifest, ShardManifestItem
from kellblog_audio.intro_outro import SPOKEN_OUTRO, spoken_intro
from kellblog_audio.publish import get_s3_client, upload_bytes, upload_file
from kellblog_audio.qa import qa_post_audio, queue_audio_rerun
from kellblog_audio.tts import (
    TTSProvider,
    get_provider,
    merge_audio_parts,
    synthesize_text_to_wav,
    wav_to_mp3,
)

OUTRO_CACHE_DIR = DATA_DIR / "tts_cache"


def audio_output_path(year: int, slug: str) -> Path:
    return AUDIO_DIR / str(year) / f"{slug}.mp3"


def shard_index_for(slug: str, shard_count: int) -> int:
    """Stable shard assignment for a slug (independent of process/list ordering)."""
    digest = hashlib.md5(slug.encode("utf-8")).hexdigest()
    return int(digest, 16) % shard_count


def _provider_cache_key(provider: TTSProvider) -> str:
    attrs = [
        provider.name,
        str(getattr(provider, "voice", "")),
        str(getattr(provider, "exaggeration", "")),
        str(getattr(provider, "reference_voice_url", "")),
    ]
    digest = hashlib.sha256("|".join(attrs).encode("utf-8")).hexdigest()[:16]
    return f"{provider.name}-{digest}"


def synthesize_outro_to_wav(provider: TTSProvider, out_wav: Path) -> None:
    """Synthesize the shared outro once per provider/voice and reuse it."""
    OUTRO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = OUTRO_CACHE_DIR / f"outro-{_provider_cache_key(provider)}.wav"
    if not cache_path.exists():
        with tempfile.TemporaryDirectory(dir=OUTRO_CACHE_DIR) as tmp:
            tmp_cache = Path(tmp) / cache_path.name
            synthesize_text_to_wav(provider, SPOKEN_OUTRO, tmp_cache)
            tmp_cache.replace(cache_path)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(cache_path, out_wav)


def validate_audio_duration(post, duration_sec: int | None) -> None:
    if not post.word_count or not duration_sec:
        return
    body_wpm = post.word_count * 60.0 / duration_sec
    if body_wpm > MAX_AUDIO_BODY_WPM:
        raise RuntimeError(
            "Implausibly short audio for "
            f"{post.slug}: {duration_sec}s for {post.word_count} body words "
            f"({body_wpm:.1f} body wpm, limit {MAX_AUDIO_BODY_WPM:g})"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_done_item(
    catalog: Catalog,
    slug: str,
    *,
    year: int | None,
    audio_etag: str | None = None,
) -> ShardManifestItem:
    post = catalog.get(slug)
    if post is None:
        raise ValueError(f"Post {slug} missing after synthesis")
    return ShardManifestItem(
        slug=slug,
        status="done",
        year=post.year if post.year is not None else year,
        audio_path=post.audio_path,
        duration_sec=post.duration_sec,
        audio_bytes=post.audio_bytes,
        audio_etag=audio_etag or post.audio_etag,
    )


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
        synthesize_outro_to_wav(provider, outro_wav)

        duration = merge_audio_parts(
            [intro_wav, body_wav, outro_wav],
            out_path,
            title=post.title or slug,
            track=post.episode_in_season,
        )
        try:
            validate_audio_duration(post, duration)
        except RuntimeError:
            out_path.unlink(missing_ok=True)
            raise

    catalog.update_post(
        slug,
        audio_path=str(out_path.relative_to(get_settings().root)),
        audio_bytes=out_path.stat().st_size,
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
    qa_first: int = 0,
    stop_on_qa_failure: bool = True,
    run_id: str | None = None,
    manifest_out: Path | None = None,
    manifest_r2_key: str | None = None,
    upload_r2: bool = False,
    progress: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    manifest_enabled = manifest_out is not None or manifest_r2_key is not None
    if manifest_enabled and not run_id:
        raise ValueError("run_id is required when writing shard manifests")
    if manifest_enabled and (shard_index is None or shard_count is None):
        raise ValueError("shard_index and shard_count are required when writing shard manifests")
    if manifest_enabled and _stop_requested.is_set():
        raise RuntimeError("Distributed synthesize stopped before completing the shard run")

    # Reset stop flag for this run (important when called multiple times in-process,
    # e.g. from the `status` command's interactive restart prompt). Clear before
    # startup so stop signals raised during model init are preserved.
    _stop_requested.clear()

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
    s3_client = get_s3_client() if (upload_r2 or manifest_r2_key) else None
    manifest_items: list[ShardManifestItem] = []
    manifest_started_at = _now_iso() if manifest_enabled else None

    ok, err = 0, 0
    qa_checked = 0
    incomplete_reason: str | None = None
    for post in posts:
        if _stop_requested.is_set():
            if progress:
                if manifest_enabled:
                    progress(
                        f"[red]Stop signal received; aborting distributed shard run "
                        f"without a manifest ({ok} ok, {err} err so far).[/red]"
                    )
                else:
                    progress(
                        f"[yellow]Stop signal received; exiting cleanly "
                        f"({ok} ok, {err} err so far).[/yellow]"
                    )
            if manifest_enabled:
                incomplete_reason = (
                    "Distributed synthesize stopped before completing the shard run"
                )
            break
        try:
            out_path = synthesize_post(
                catalog, post.slug, provider_name, force=force, provider=provider
            )
            if out_path is None:
                if manifest_enabled:
                    manifest_items.append(
                        ShardManifestItem(
                            slug=post.slug,
                            status="skip",
                            year=post.year,
                            error=post.audio_error,
                        )
                    )
                continue

            audio_etag: str | None = None
            if qa_checked < qa_first:
                qa_checked += 1
                qa_result = qa_post_audio(catalog, post.slug)
                if not qa_result.passed:
                    queue_audio_rerun(catalog, post.slug, qa_result.reason)
                    err += 1
                    if manifest_enabled:
                        manifest_items.append(
                            ShardManifestItem(
                                slug=post.slug,
                                status="error",
                                year=post.year,
                                error=qa_result.reason,
                            )
                        )
                    if progress:
                        progress(
                            f"qa failed {post.slug}; queued for rerun: "
                            f"{qa_result.reason}"
                        )
                    if stop_on_qa_failure:
                        if manifest_enabled:
                            incomplete_reason = (
                                "Distributed synthesize halted after QA failure for "
                                f"{post.slug}: {qa_result.reason}"
                            )
                        break
                    continue
                if progress:
                    progress(f"qa passed {post.slug}: {qa_result.reason}")
            if upload_r2:
                client = s3_client or get_s3_client()
                audio_key = f"audio/{post.year or 1970}/{post.slug}.mp3"
                audio_etag = upload_file(client, out_path, audio_key, "audio/mpeg")
                update_fields = {"backfill_run_id": run_id} if run_id else {}
                if audio_etag is not None:
                    update_fields["audio_etag"] = audio_etag
                if update_fields:
                    catalog.update_post(post.slug, **update_fields)
            if manifest_enabled:
                manifest_items.append(
                    _manifest_done_item(
                        catalog,
                        post.slug,
                        year=post.year,
                        audio_etag=audio_etag,
                    )
                )
            if progress:
                rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
                try:
                    import torch

                    mps_mb = (
                        torch.mps.current_allocated_memory() // 1024 // 1024
                        if torch.backends.mps.is_available()
                        else 0
                    )
                except Exception:
                    mps_mb = 0
                progress(
                    f"synthesized {post.slug}  "
                    f"[rss={rss_mb}MB mps={mps_mb}MB]"
                )
            ok += 1
        except Exception as e:
            catalog.update_post(post.slug, audio_status="error", audio_error=str(e)[:500])
            err += 1
            if manifest_enabled:
                manifest_items.append(
                    ShardManifestItem(
                        slug=post.slug,
                        status="error",
                        year=post.year,
                        error=str(e)[:500],
                    )
                )
            if progress:
                progress(f"error {post.slug}: {e}")

    if manifest_enabled and incomplete_reason:
        raise RuntimeError(incomplete_reason)

    if manifest_enabled:
        manifest = ShardManifest(
            run_id=run_id or "local",
            shard_index=shard_index,
            shard_count=shard_count,
            provider=getattr(provider, "name", provider_name),
            started_at=manifest_started_at,
            finished_at=_now_iso(),
            items=manifest_items,
        )
        manifest_json = manifest.to_json()
        if manifest_out is not None:
            manifest_out.parent.mkdir(parents=True, exist_ok=True)
            manifest_out.write_text(manifest_json, encoding="utf-8")
        if manifest_r2_key is not None:
            client = s3_client or get_s3_client()
            upload_bytes(client, manifest_json.encode("utf-8"), manifest_r2_key, "application/json")
    return ok, err
