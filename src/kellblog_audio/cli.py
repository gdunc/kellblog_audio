"""Typer CLI for kellblog-audio."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from kellblog_audio.bakeoff import run_bakeoff
from kellblog_audio.bakeoff_voices import BAKEOFF_SLUGS
from kellblog_audio.bakeoff_html import write_bakeoff_page
from kellblog_audio.catalog import Catalog
from kellblog_audio.config import (
    CATALOG_PATH,
    QA_TRANSCRIPTS_DIR,
    TTS_PROVIDER,
    get_settings,
)
from kellblog_audio.maintenance import reset_generated_audio
from kellblog_audio.ingest import ingest_all
from kellblog_audio.publish import (
    backup_catalog,
    publish_local,
    publish_to_r2,
    restore_catalog,
)
from kellblog_audio.qa import qa_post_audio, queue_audio_rerun
from kellblog_audio.review_html import collect_review_items, write_review_page
from kellblog_audio.synthesize import synthesize_batch
from kellblog_audio.tts import list_available_providers

app = typer.Typer(
    name="kellblog-audio",
    help="Kellblog → podcast pipeline (ingest, TTS, publish)",
)
console = Console()


def _is_synthesize_running() -> bool:
    """Return True if a 'kellblog-audio synthesize' process is currently active."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "kellblog-audio synthesize"],
            capture_output=True,
        )
        # pgrep exits 0 when at least one match is found, 1 when none
        return result.returncode == 0
    except Exception:
        return False


def _catalog() -> Catalog:
    settings = get_settings()
    settings.ensure_dirs()
    cat = Catalog(settings.catalog_path)
    cat.init_schema()
    return cat


@app.command()
def ingest(
    slug: Optional[str] = typer.Option(None, help="Single post slug"),
    limit: Optional[int] = typer.Option(None, help="Max posts to ingest"),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Re-fetch and re-clean already ingested posts",
    ),
) -> None:
    """Sync sitemap and fetch/extract posts."""
    if slug and limit:
        ingest_all(_catalog(), slug=slug, limit=limit, force_refresh=refresh)
    elif slug:
        ingest_all(_catalog(), slug=slug, force_refresh=refresh)
    elif limit:
        ingest_all(_catalog(), limit=limit, force_refresh=refresh)
    else:
        ingest_all(_catalog(), force_refresh=refresh)


@app.command()
def synthesize(
    pending: bool = typer.Option(True, "--pending/--all", help="Only pending/stale"),
    year: Optional[int] = typer.Option(None, "--year", "-y"),
    slug: Optional[str] = typer.Option(None, "--slug", "-s"),
    force: bool = typer.Option(False, "--force", help="Re-synthesize even if done"),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="kokoro | chatterbox"
    ),
    limit: Optional[int] = typer.Option(None, help="Max episodes"),
    qa_first: int = typer.Option(
        0,
        "--qa-first",
        help="Transcribe and score the first N newly synthesized episodes",
    ),
    shard: Optional[str] = typer.Option(
        None, "--shard", help="Parallel worker shard as i/N, e.g. 0/2 and 1/2"
    ),
) -> None:
    """Run TTS for matching posts."""
    shard_index = shard_count = None
    if shard:
        try:
            i_str, n_str = shard.split("/")
            shard_index, shard_count = int(i_str), int(n_str)
        except ValueError as exc:
            raise typer.BadParameter("--shard must be i/N, e.g. 0/2") from exc
        if not (0 <= shard_index < shard_count):
            raise typer.BadParameter("--shard i must satisfy 0 <= i < N")
    cat = _catalog()
    ok, err = synthesize_batch(
        cat,
        pending_only=pending,
        year=year,
        slug=slug,
        force=force,
        provider_name=provider,
        limit=limit,
        shard_index=shard_index,
        shard_count=shard_count,
        qa_first=qa_first,
        progress=console.print,
    )
    console.print(f"Done: {ok} ok, {err} errors (provider={provider or TTS_PROVIDER})")


@app.command()
def publish(
    local_only: bool = typer.Option(
        False, "--local-only", help="Write feed.xml locally only"
    ),
    skip_audio: bool = typer.Option(
        False, "--skip-audio", help="Only rebuild/upload feed"
    ),
) -> None:
    """Build RSS and upload to R2."""
    cat = _catalog()
    if local_only:
        path = publish_local(cat)
        console.print(f"Wrote {path}")
        return
    try:
        url = publish_to_r2(cat, upload_audio=not skip_audio)
        console.print(f"Published feed: {url}")
    except RuntimeError as e:
        console.print(f"[yellow]R2 not configured: {e}[/yellow]")
        path = publish_local(cat)
        console.print(f"Wrote local feed: {path}")


@app.command()
def status() -> None:
    """Show pipeline counts and synthesis process state."""
    cat = _catalog()
    c = cat.counts()
    running = _is_synthesize_running()

    table = Table(title="Kellblog Audio Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")
    for k, v in c.items():
        table.add_row(k.replace("_", " "), str(v))
    process_label = "[green]Running[/green]" if running else "[red]Stopped[/red]"
    table.add_row("synthesis process", process_label)
    console.print(table)
    console.print(f"TTS provider: {TTS_PROVIDER}")
    console.print(f"Catalog: {CATALOG_PATH}")

    if not running and c["audio_pending"] > 0:
        restart = typer.confirm(
            "\nSynthesis is not running. Would you like to restart it now?",
            default=False,
        )
        if restart:
            console.print("Restarting synthesis (synthesize --pending) …")
            ok, err = synthesize_batch(cat, pending_only=True, progress=console.print)
            console.print(f"Done: {ok} ok, {err} errors (provider={TTS_PROVIDER})")


@app.command("reset-audio")
def reset_audio(
    yes: bool = typer.Option(False, "--yes", help="Confirm destructive reset"),
    keep_files: bool = typer.Option(False, "--keep-files", help="Keep local MP3 files"),
) -> None:
    """Reset generated audio state so all non-skip posts can be re-synthesized."""
    if not yes:
        typer.confirm(
            "Reset all generated audio metadata and delete local MP3 files?",
            abort=True,
        )
    result = reset_generated_audio(_catalog(), delete_files=not keep_files)
    console.print(
        "Reset "
        f"{result.reset_posts} posts; deleted {result.deleted_files} files; "
        f"{result.missing_files} referenced files were already missing."
    )


@app.command("qa-audio")
def qa_audio(
    slug: Optional[str] = typer.Option(None, "--slug", "-s"),
    limit: int = typer.Option(5, "--limit", help="Max done episodes to QA"),
    rerun_failed: bool = typer.Option(
        False,
        "--rerun-failed",
        help="Mark failed QA episodes stale so synthesize --pending regenerates them",
    ),
) -> None:
    """Transcribe generated audio with local Whisper and compare it to source text."""
    cat = _catalog()
    posts = [cat.get(slug)] if slug else cat.list_by_filter(audio_status="done")[:limit]
    for post in posts:
        if not post:
            continue
        result = qa_post_audio(cat, post.slug)
        if rerun_failed and not result.passed:
            queue_audio_rerun(cat, post.slug, result.reason)
        style = "green" if result.passed else "red"
        rerun_note = " queued-for-rerun" if rerun_failed and not result.passed else ""
        console.print(
            f"[{style}]{post.slug}: {result.reason}{rerun_note} "
            f"(coverage={result.source_coverage:.1%}, "
            f"tail={result.tail_similarity:.1%}, "
            f"repeat3={result.max_repeated_three_gram})[/{style}]"
        )


@app.command("qa-stats")
def qa_stats() -> None:
    """Summarize local QA artifacts and catalog rerun state."""
    cat = _catalog()
    done_slugs = {p.slug for p in cat.list_by_filter(audio_status="done")}
    stale_reruns = [
        p
        for p in cat.list_by_filter(audio_status="stale")
        if p.audio_error and p.audio_error.startswith("Audio QA failed")
    ]

    reports = []
    for path in sorted(QA_TRANSCRIPTS_DIR.glob("*.qa.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        slug = path.name[: -len(".qa.json")]
        reports.append((slug, data))

    report_slugs = {slug for slug, _data in reports}
    missing = sorted(done_slugs - report_slugs)
    failed = [(slug, data) for slug, data in reports if data.get("passed") is not True]
    passed = [(slug, data) for slug, data in reports if data.get("passed") is True]
    coverage = [float(data["source_coverage"]) for _slug, data in reports]
    tail = [float(data["tail_similarity"]) for _slug, data in reports]

    table = Table(title="Kellblog Audio QA Stats")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("done episodes", str(len(done_slugs)))
    table.add_row("qa artifacts", str(len(reports)))
    table.add_row("qa pass", str(len(passed)))
    table.add_row("qa fail", str(len(failed)))
    table.add_row("done missing qa", str(len(missing)))
    table.add_row("queued QA reruns", str(len(stale_reruns)))
    table.add_row("coverage min", _format_pct(_quantile(coverage, 0.0)))
    table.add_row("coverage p10", _format_pct(_quantile(coverage, 0.10)))
    table.add_row("tail min", _format_pct(_quantile(tail, 0.0)))
    table.add_row("tail p10", _format_pct(_quantile(tail, 0.10)))
    console.print(table)

    for slug, data in failed[:10]:
        console.print(
            "[red]"
            f"failed {slug}: coverage={float(data.get('source_coverage', 0)):.1%}, "
            f"tail={float(data.get('tail_similarity', 0)):.1%}, "
            f"repeat3={data.get('max_repeated_three_gram')}, "
            f"reason={data.get('reason')}"
            "[/red]"
        )
    for slug in missing[:10]:
        console.print(f"[yellow]missing QA {slug}[/yellow]")


@app.command("queue-qa-concerns")
def queue_qa_concerns(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Mark concerning episodes stale so synthesize --pending regenerates them",
    ),
    limit: Optional[int] = typer.Option(None, help="Max episodes to queue"),
) -> None:
    """Dry-run or queue QA warning episodes for regeneration."""
    cat = _catalog()
    concerning = [item for item in collect_review_items(cat) if item.concerns]
    if limit is not None:
        concerning = concerning[:limit]

    if not concerning:
        console.print("[green]No QA concern episodes found.[/green]")
        return

    action = "Queued" if apply else "Would queue"
    for item in concerning:
        reason = "; ".join(item.concerns)
        if apply:
            queue_audio_rerun(cat, item.post.slug, reason)
        console.print(f"{action} {item.post.slug}: {reason}")

    if not apply:
        console.print("\nRun again with --apply to mark these episodes stale.")


@app.command("review-page")
def review_page() -> None:
    """Regenerate output/index.html for collaborator listening review."""
    page = write_review_page(_catalog())
    console.print(f"Wrote {page}")


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = round((len(ordered) - 1) * q)
    return ordered[idx]


def _format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


@app.command("restore-catalog")
def restore_catalog_cmd() -> None:
    """Download latest SQLite catalog backup from R2."""
    cat = _catalog()
    if restore_catalog(cat):
        console.print(f"Restored catalog to {cat.path}")
    else:
        console.print("No backup found in R2")


@app.command("backup-catalog")
def backup_catalog_cmd() -> None:
    """Upload SQLite catalog to R2."""
    cat = _catalog()
    key = backup_catalog(cat)
    console.print(f"Backed up to s3://{key}")


@app.command()
def providers() -> None:
    """List installed TTS engines available for bake-off."""
    available = list(list_available_providers())
    if not available:
        console.print("[yellow]No TTS extras installed.[/yellow]")
        console.print("Run: uv sync --extra compare")
        return
    for name in available:
        console.print(f"  • {name}")
    console.print("\nInstall all comparison engines: uv sync --extra compare")


@app.command()
def bakeoff(
    slugs: Optional[list[str]] = typer.Option(
        None, "--slug", "-s", help="Post slugs (repeatable)"
    ),
    html_only: bool = typer.Option(
        False, "--html-only", help="Regenerate index.html from existing MP3s"
    ),
) -> None:
    """Generate TTS comparison samples and listening page."""
    cat = _catalog()
    if html_only:
        page = write_bakeoff_page(cat)
        console.print(f"Wrote {page}")
        console.print("Serve: cd output/bakeoff && python3 -m http.server 8765")
        return
    use_slugs = slugs or list(BAKEOFF_SLUGS)
    run_bakeoff(cat, use_slugs)


@app.command("bakeoff-serve")
def bakeoff_serve(
    port: int = typer.Option(8765, help="HTTP port"),
) -> None:
    """Serve the bake-off comparison page locally."""
    import http.server
    import socketserver

    from kellblog_audio.config import BAKEOFF_DIR

    BAKEOFF_DIR.mkdir(parents=True, exist_ok=True)
    if not (BAKEOFF_DIR / "index.html").exists():
        write_bakeoff_page(_catalog())
    os.chdir(BAKEOFF_DIR)
    console.print(f"Open http://localhost:{port}/index.html")
    with socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()


@app.command("run-backfill")
def run_backfill(
    limit: Optional[int] = typer.Option(
        None, help="Limit posts (for testing); omit for full archive"
    ),
    local_publish: bool = typer.Option(
        True, "--local-publish/--r2-publish", help="Publish feed locally vs R2"
    ),
) -> None:
    """Full pipeline: ingest → synthesize → publish."""
    cat = _catalog()
    console.print("Step 1/3: ingest")
    ingest_all(cat, limit=limit)
    console.print("Step 2/3: synthesize")
    synthesize_batch(cat, pending_only=True, limit=limit, progress=console.print)
    console.print("Step 3/3: publish")
    if local_publish:
        path = publish_local(cat)
        console.print(f"Feed: {path}")
    else:
        try:
            url = publish_to_r2(cat)
            console.print(f"Feed: {url}")
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")


if __name__ == "__main__":
    app()
