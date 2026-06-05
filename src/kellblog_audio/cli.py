"""Typer CLI for kellblog-audio."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from kellblog_audio.bakeoff import run_bakeoff
from kellblog_audio.bakeoff_voices import BAKEOFF_SLUGS
from kellblog_audio.bakeoff_html import write_bakeoff_page
from kellblog_audio.catalog import Catalog
from kellblog_audio.config import CATALOG_PATH, TTS_PROVIDER, get_settings
from kellblog_audio.ingest import ingest_all
from kellblog_audio.publish import (
    backup_catalog,
    publish_local,
    publish_to_r2,
    restore_catalog,
)
from kellblog_audio.synthesize import synthesize_batch
from kellblog_audio.tts import list_available_providers

app = typer.Typer(
    name="kellblog-audio",
    help="Kellblog → podcast pipeline (ingest, TTS, publish)",
)
console = Console()


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
) -> None:
    """Sync sitemap and fetch/extract posts."""
    if slug and limit:
        ingest_all(_catalog(), slug=slug, limit=limit)
    elif slug:
        ingest_all(_catalog(), slug=slug)
    elif limit:
        ingest_all(_catalog(), limit=limit)
    else:
        ingest_all(_catalog())


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
    """Show pipeline counts."""
    cat = _catalog()
    c = cat.counts()
    table = Table(title="Kellblog Audio Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")
    for k, v in c.items():
        table.add_row(k.replace("_", " "), str(v))
    console.print(table)
    console.print(f"TTS provider: {TTS_PROVIDER}")
    console.print(f"Catalog: {CATALOG_PATH}")


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
