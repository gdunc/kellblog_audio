# Distributed Backfill Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automated, single-writer distributed backfill support using Chatterbox, R2 coordination, and free public GitHub Actions runners.

**Architecture:** Keep SQLite as the authoritative catalog, but stop using it as a multi-writer cross-machine state store. Shard workers upload canonical audio and run-scoped manifests to R2; a finalizer merges manifests into one catalog and publishes once.

**Tech Stack:** Python 3.11+, Typer, SQLite, boto3/R2, GitHub Actions, pytest

---

## File map
- Modify: `src/kellblog_audio/catalog.py:12-42,45-69,95-120,206-209`
- Modify: `src/kellblog_audio/publish.py:26-132`
- Modify: `src/kellblog_audio/podcast.py:56-151`
- Create: `src/kellblog_audio/distributed_backfill.py`
- Modify: `src/kellblog_audio/synthesize.py:49-56,96-146,149-243`
- Modify: `src/kellblog_audio/cli.py:87-154,338-353`
- Create: `tests/test_distributed_backfill.py`
- Create: `tests/test_cli_distributed.py`
- Modify: `tests/test_rss.py`
- Modify: `tests/test_synthesize_quality.py`
- Create: `.github/workflows/backfill-distributed.yml`
- Modify: `README.md:48-58,107-129`
- Modify: `docs/BACKFILL.md:5-57`

### Task 1: Catalog metadata and keyed R2 catalog sync
**Files:**
- Modify: `src/kellblog_audio/catalog.py:12-42,45-69,95-120,206-209`
- Modify: `src/kellblog_audio/publish.py:26-132`
- Modify: `src/kellblog_audio/podcast.py:132-151`
- Test: `tests/test_distributed_backfill.py`, `tests/test_rss.py`

- [ ] **Step 1: Write the failing tests**

```python
assert backup_catalog(cat, key="backfill/runs/r1/baseline/catalog.sqlite") == "backfill/runs/r1/baseline/catalog.sqlite"
assert restore_catalog(cat, key="backfill/runs/r1/baseline/catalog.sqlite") is True
xml = ET.fromstring(build_feed(cat, local_audio=False))
assert xml.find(".//enclosure").attrib["length"] == "1234"
```

- [ ] **Step 2: Run the tests to confirm failure**
Run: `uv run pytest tests/test_distributed_backfill.py tests/test_rss.py -v`
Expected: FAIL on missing `key` support and missing remote-length fallback.

- [ ] **Step 3: Add the minimal implementation**

```python
@dataclass
class PostRow:
    audio_bytes: int | None = None
    audio_etag: str | None = None
    backfill_run_id: str | None = None
```

- [ ] **Step 4: Extend catalog backup/restore and feed length lookup**

```python
def backup_catalog(catalog: Catalog, key: str | None = None) -> str:
    resolved_key = key or f"backup/catalog-{datetime.now(timezone.utc):%Y-%m-%d}.sqlite"
    client.upload_file(str(catalog.path), R2_BUCKET, resolved_key, ExtraArgs={"ContentType": "application/x-sqlite3"})
    return resolved_key

def restore_catalog(catalog: Catalog, key: str | None = None) -> bool:
    resolved_key = key or _latest_catalog_key(client)
    if not resolved_key:
        return False
    client.download_file(R2_BUCKET, resolved_key, str(catalog.path))
    return True

def _remote_length(post: PostRow) -> int: return post.audio_bytes or 0
```

- [ ] **Step 5: Re-run the targeted tests**
Run: `uv run pytest tests/test_distributed_backfill.py tests/test_rss.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**
Run: `git add src/kellblog_audio/catalog.py src/kellblog_audio/publish.py src/kellblog_audio/podcast.py tests/test_distributed_backfill.py tests/test_rss.py && git commit -m "feat: add run-scoped catalog sync primitives"`

### Task 2: Run-scoped manifests and baseline/finalizer helpers
**Files:**
- Create: `src/kellblog_audio/distributed_backfill.py`
- Test: `tests/test_distributed_backfill.py`

- [ ] **Step 1: Write the failing tests for manifest merge and duplicate detection**

```python
result = merge_shard_manifests(cat, run_id="r1", manifests=[m0, m1])
assert result.done == 2 and result.errors == 1
with pytest.raises(ValueError, match="duplicate slug"):
    merge_shard_manifests(cat, run_id="r1", manifests=[m0, dup])
```

- [ ] **Step 2: Run the tests to confirm failure**
Run: `uv run pytest tests/test_distributed_backfill.py -v`
Expected: FAIL on missing module/functions.

- [ ] **Step 3: Add manifest and merge helpers**

```python
@dataclass
class ShardManifestItem: slug: str; status: str; audio_path: str | None = None

def create_backfill_baseline(catalog: Catalog, run_id: str) -> str:
    ingest_all(catalog)
    return backup_catalog(catalog, key=f"backfill/runs/{run_id}/baseline/catalog.sqlite")

def merge_shard_manifests(catalog: Catalog, run_id: str, manifests: list[Path]) -> MergeResult:
    seen: set[str] = set()
    for manifest_path in manifests:
        apply_manifest(catalog, run_id, manifest_path, seen)
    return summarize_merge(catalog, run_id)
```

- [ ] **Step 4: Re-run the targeted tests**
Run: `uv run pytest tests/test_distributed_backfill.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
Run: `git add src/kellblog_audio/distributed_backfill.py tests/test_distributed_backfill.py && git commit -m "feat: add distributed backfill manifest merge helpers"`

### Task 3: Synthesize/CLI support for run id, manifest upload, and final publish semantics
**Files:**
- Modify: `src/kellblog_audio/synthesize.py:49-56,96-146,149-243`
- Modify: `src/kellblog_audio/cli.py:87-154,338-353`
- Modify: `src/kellblog_audio/publish.py:62-104`
- Test: `tests/test_synthesize_quality.py`, `tests/test_distributed_backfill.py`, `tests/test_cli_distributed.py`

- [ ] **Step 1: Write the failing tests for distributed synth output**

```python
ok, err = synthesize_batch(cat, shard_index=0, shard_count=2, run_id="r1", manifest_out=path, manifest_r2_key="k")
assert ok == 1 and json.loads(path.read_text())["run_id"] == "r1"
result = runner.invoke(app, ["restore-catalog", "--run-id", "r1", "--kind", "baseline"])
assert result.exit_code == 0
```

- [ ] **Step 2: Run the tests to confirm failure**
Run: `uv run pytest tests/test_synthesize_quality.py tests/test_distributed_backfill.py tests/test_cli_distributed.py -v`
Expected: FAIL on unknown arguments and missing publish bookkeeping.

- [ ] **Step 3: Add synth/output plumbing and CLI wiring**

```python
def synthesize_batch(catalog: Catalog, *, run_id: str | None = None, manifest_out: Path | None = None, manifest_r2_key: str | None = None, upload_r2: bool = False, **kwargs) -> tuple[int, int]:
    manifest = ShardManifest(run_id=run_id, shard_index=kwargs.get("shard_index"), shard_count=kwargs.get("shard_count"), provider=(kwargs.get("provider_name") or TTS_PROVIDER), items=[])
    manifest.items.append(ShardManifestItem(slug=post.slug, status="done", audio_path=str(out_path), duration_sec=duration, audio_bytes=out_path.stat().st_size))
    if manifest_out:
        manifest_out.write_text(manifest.to_json(), encoding="utf-8")
    if manifest_r2_key:
        upload_bytes(get_s3_client(), manifest.to_json().encode("utf-8"), manifest_r2_key, "application/json")

@app.command("create-backfill-baseline")
def create_backfill_baseline_cmd(run_id: str | None = typer.Option(None, "--run-id")) -> None:
    if not run_id:
        raise typer.BadParameter("--run-id is required")
    console.print(f"Backed up to s3://{create_backfill_baseline(_catalog(), run_id)}")

@app.command("merge-shard-manifests")
def merge_shard_manifests_cmd(run_id: str | None = typer.Option(None, "--run-id"), manifest_dir: Path | None = typer.Option(None, "--manifest-dir")) -> None:
    if not run_id or not manifest_dir:
        raise typer.BadParameter("--run-id and --manifest-dir are required")
    result = merge_shard_manifests(_catalog(), run_id, sorted(manifest_dir.glob("*.json")))
    console.print(f"Merged {result.done} done / {result.errors} errors")
```

- [ ] **Step 4: Make `publish --skip-audio` mark existing done rows published after a successful feed upload**

```python
if not upload_audio:
    for post in catalog.list_by_filter(audio_status="done"):
        catalog.mark_feed_published(post.slug)
```

- [ ] **Step 5: Re-run the targeted tests**
Run: `uv run pytest tests/test_synthesize_quality.py tests/test_distributed_backfill.py tests/test_cli_distributed.py tests/test_rss.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**
Run: `git add src/kellblog_audio/synthesize.py src/kellblog_audio/cli.py src/kellblog_audio/publish.py tests/test_synthesize_quality.py tests/test_distributed_backfill.py tests/test_cli_distributed.py tests/test_rss.py && git commit -m "feat: wire distributed synthesis and final publish flow"`

### Task 4: GitHub Actions workflow and operator docs
**Files:**
- Create: `.github/workflows/backfill-distributed.yml`
- Modify: `README.md:48-58,107-129`
- Modify: `docs/BACKFILL.md:5-57`

- [ ] **Step 1: Add the workflow with prepare, matrix synthesize, and finalize jobs**

```yaml
concurrency: distributed-backfill
jobs: { prepare: {}, synthesize: { strategy: { fail-fast: false } }, finalize: {} }
```

- [ ] **Step 2: Document the default GHA-only flow and optional `local_helper_shards` Mac helper path**

```md
uv run kellblog-audio synthesize --pending --run-id <run_id> --shard 0/N --upload-r2 --manifest-r2-key backfill/runs/<run_id>/manifests/shard-0-of-N.json
```

- [ ] **Step 3: Run the regression suite covering touched behavior**
Run: `uv run pytest tests/test_distributed_backfill.py tests/test_synthesize_quality.py tests/test_rss.py tests/test_audio_reset.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**
Run: `git add .github/workflows/backfill-distributed.yml README.md docs/BACKFILL.md && git commit -m "docs: add distributed backfill workflow and operator guide"`

### Final verification
- [ ] Run: `uv run pytest tests/test_distributed_backfill.py tests/test_cli_distributed.py tests/test_synthesize_quality.py tests/test_rss.py tests/test_audio_reset.py -v`
- [ ] Run: `uv run python -m kellblog_audio.cli --help`
- [ ] Confirm the new plan matches `docs/superpowers/specs/2026-06-29-distributed-backfill-design.md` exactly
