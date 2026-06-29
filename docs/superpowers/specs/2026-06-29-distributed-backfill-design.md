# Distributed Backfill Automation — Design Spec
**Date:** 2026-06-29  
**Status:** Draft for review

## Goal
Automate archive-scale **Chatterbox** synthesis across free public-repo `ubuntu-latest` runners, with an optional local M-series Mac helper, while using Cloudflare R2 for coordination/storage and reducing human intervention to a single workflow dispatch.

## Requirements
- Keep using **Chatterbox**.
- Use public GitHub Actions free runners as much as practical.
- Keep deterministic `synthesize --shard i/N` partitioning.
- Remove unsafe multi-writer whole-SQLite coordination.
- Publish exactly once per backfill run.
- Support both fully automated GHA-only runs and optional Mac+GHA hybrid runs.

## Non-goals
- Replacing SQLite with a network database.
- Reworking ingest or TTS internals.
- Supporting overlapping backfill runs against the same feed.

## Problem Summary
Current sharding is compute-safe but not state-safe across machines. `restore-catalog` and `backup-catalog` copy whole SQLite files, so independent workers can overwrite one another. Fully remote finalization also needs feed metadata that does not depend on local MP3 files.

## Design Overview
Use a **single-writer finalizer** pattern:
1. A prepare job creates a run-scoped baseline catalog.
2. Shard workers restore that baseline, synthesize only their shard, upload audio to canonical R2 audio keys, and write shard manifests to R2.
3. One finalizer restores the same baseline, merges manifests into one authoritative catalog, validates completeness, publishes once, and uploads the final catalog backup.

## New/Changed Data Model
Add catalog columns:
- `audio_bytes INTEGER` — final MP3 size for enclosure length without local file access.
- `audio_etag TEXT NULL` — optional R2 ETag for verification/debugging.
- `backfill_run_id TEXT NULL` — last run that produced the current audio row.

## R2 Layout
Keep existing daily `backup/catalog-YYYY-MM-DD.sqlite` for normal ops, and add run-scoped coordination keys:
- `backfill/runs/<run_id>/baseline/catalog.sqlite`
- `backfill/runs/<run_id>/manifests/shard-<i>-of-<N>.json`
- `backfill/runs/<run_id>/reports/summary.json`
- `backfill/runs/<run_id>/catalog/final.sqlite`
- canonical published audio remains `audio/<year>/<slug>.mp3`
`run_id` should be workflow-scoped, e.g. `20260629T061700Z-<github_run_id>`.

## CLI Changes
### 1. `restore-catalog` / `backup-catalog`
Extend both commands with run-scoped addressing so existing semantics remain usable:
- `restore-catalog --key <r2-key>` or `--run-id <id> --kind baseline|final`
- `backup-catalog --key <r2-key>` or `--run-id <id> --kind baseline|final`

### 2. `create-backfill-baseline`
Creates the authoritative baseline for a run:
- restores latest daily catalog if present
- runs `ingest`
- uploads the resulting SQLite file to `backfill/runs/<run_id>/baseline/catalog.sqlite`
- writes a small JSON summary with pending/stale counts

### 3. `synthesize`
Extend existing command with optional flags:
- `--run-id <id>`
- `--upload-r2` — upload each completed MP3 to canonical `audio/<year>/<slug>.mp3`
- `--manifest-out <path>` — write shard results JSON locally
- `--manifest-r2-key <key>` — upload the manifest to R2 when synthesis completes
Behavior stays backward-compatible when omitted.

### 4. `merge-shard-manifests`
Inputs: baseline catalog, run id, manifest source. Applies shard outcomes deterministically:
- `done` rows set `audio_status`, `audio_path`, `duration_sec`, `audio_bytes`, `audio_etag`, `audio_error=NULL`, `backfill_run_id`
- `error` rows set `audio_status=error`, `audio_error`
- duplicate/conflicting entries for the same slug fail fast

### 5. `publish`
Enhance distributed finalization support:
- `publish --skip-audio` must mark existing `done` rows as feed-published after successful feed upload
- feed generation should prefer `audio_bytes` when local files are absent
- review page / feed generation must not require downloading all MP3s locally

## Shard Manifest Format
Each JSON manifest contains:
- `run_id`, `shard_index`, `shard_count`, `provider`, `started_at`, `finished_at`
- `items[]` with `slug`, `year`, `status`, `audio_path`, `duration_sec`, `audio_bytes`, `audio_etag`, `error`
- `counts` summary (`done`, `error`, `skipped`)

## GitHub Actions Workflow
Add `.github/workflows/backfill-distributed.yml` with `concurrency` enabled and `workflow_dispatch` inputs:
- `shard_count` (default `6`)
- `qa_first` (default `0`)
- optional `year`
- optional `local_helper_shards` (default empty; example `0`)

### Job 1: `prepare`
- checkout, setup `uv`, install `ffmpeg` + `espeak-ng`, `uv sync --frozen --extra chatterbox`
- compute `run_id`
- run `create-backfill-baseline`

### Job 2: `synthesize`
- `needs: prepare`
- `strategy.fail-fast: false`
- matrix covers all shards **except** any listed in `local_helper_shards`
- each runner restores the run baseline and executes Chatterbox on CPU:
  `KELLBLOG_TTS_PROVIDER=chatterbox KELLBLOG_CHATTERBOX_DEVICE=cpu uv run kellblog-audio synthesize --pending --run-id "$RUN_ID" --shard "${{ matrix.shard }}/${{ inputs.shard_count }}" --upload-r2 --manifest-out manifest.json --manifest-r2-key "backfill/runs/$RUN_ID/manifests/shard-${{ matrix.shard }}-of-${{ inputs.shard_count }}.json"`
- upload `manifest.json` as a small artifact for debugging only

### Job 3: `finalize`
- `needs: synthesize`
- restore the run baseline
- fetch expected manifests from R2
- fail if any required manifest is missing or duplicated
- run `merge-shard-manifests`
- run `uv run kellblog-audio publish --skip-audio`
- upload merged catalog to `backfill/runs/<run_id>/catalog/final.sqlite` and daily backup
- emit a step-summary report

## Optional Local Mac Helper
Default operation is fully automated **GHA-only**. Hybrid mode is optional acceleration.
- reserve shard(s) through `local_helper_shards`
- on the Mac, run exactly one shard with `KELLBLOG_CHATTERBOX_DEVICE=auto`
- recommended command:
  `KELLBLOG_TTS_PROVIDER=chatterbox KELLBLOG_CHATTERBOX_DEVICE=auto uv run kellblog-audio synthesize --pending --run-id <run_id> --shard 0/N --upload-r2 --manifest-out local-shard.json --manifest-r2-key backfill/runs/<run_id>/manifests/shard-0-of-N.json`
- do **not** run multiple MPS shards locally; one MPS worker remains the recommended local mode

## Failure Handling
- workflow `concurrency` prevents overlapping distributed backfills
- finalizer refuses to publish if any required manifest is missing/duplicate
- rerunning a failed shard overwrites only that shard's manifest and audio objects
- rerunning finalizer from the same manifests must reproduce the same merged catalog

## Free-Tier Strategy
- prefer Ubuntu GHA runners for most shard compute because standard runners on public repos are free
- use GitHub artifacts only for small manifests/logging; use R2 for audio and catalog coordination
- default `shard_count` should target sub-6-hour jobs; start at `6` and tune only if needed
- keep the Mac optional so unattended GHA-only runs remain possible

## Success Criteria
- one workflow dispatch can complete an archive backfill without manual catalog syncing
- hybrid Mac+GHA runs use the same run-scoped protocol and require no manual merge
- publish happens once, after manifest validation
- feed generation works without local copies of all MP3s
- existing non-distributed commands remain backward-compatible
