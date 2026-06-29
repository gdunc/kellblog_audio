# Full archive backfill

~778 posts, ~117 hours of audio, ~8–12 GB MP3 at 128 kbps mono.

## Default flow: distributed GitHub Actions

Use `.github/workflows/backfill-distributed.yml` as the default archive path.

- Dispatch with the default inputs unless you have a specific reason to change them: `shard_count=6`, `qa_first=0`, blank `year`, blank `local_helper_shards`.
- The default path uses free public GitHub-hosted Ubuntu runners and keeps **Chatterbox** as the synthesis model.
- `prepare` creates `backfill/runs/<run_id>/baseline/catalog.sqlite`.
- Each shard runner restores that baseline, runs `synthesize --pending --run-id <run_id> --shard i/N --upload-r2`, and uploads a shard manifest to `backfill/runs/<run_id>/manifests/`.
- `finalize` restores the same baseline, validates that every shard manifest exists exactly once, merges them, runs `uv run kellblog-audio publish --skip-audio`, uploads `backfill/runs/<run_id>/catalog/final.sqlite`, and writes `backfill/runs/<run_id>/reports/summary.json`.

This path does **not** require pre-existing local audio. The shard jobs upload only the MP3s they synthesize for that run.

## Optional local Mac helper shard

Hybrid mode is optional acceleration. Leave `local_helper_shards` empty unless you want to reserve a shard for a local M-series Mac.

1. Dispatch the workflow with `local_helper_shards` set to the shard indexes you will run locally, for example `0`.
2. Wait for the `prepare` job to finish and copy the `run_id` from its job summary.
3. On the Mac, use a clean checkout/worktree of the same branch/commit. Do **not** commit or push unrelated changes as part of the helper run.
4. Before running `restore-catalog` or `synthesize --upload-r2`, make sure the Mac already has working local `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET` configured.
5. Restore the run baseline locally before synthesizing:

```bash
uv sync --frozen --extra chatterbox
uv run kellblog-audio restore-catalog --run-id <run_id> --kind baseline
```

6. Run exactly one local MPS shard using the same `N` and optional `--year` as the workflow dispatch:

```bash
export KELLBLOG_TTS_PROVIDER=chatterbox
export KELLBLOG_CHATTERBOX_DEVICE=auto
uv run kellblog-audio synthesize --pending \
  --run-id <run_id> \
  --shard 0/N \
  --upload-r2 \
  --manifest-out artifacts/local-shard-0.json \
  --manifest-r2-key backfill/runs/<run_id>/manifests/shard-0-of-N.json
```

7. Do **not** run multiple local MPS shards at once; one MPS worker is still the recommended Mac mode.
8. Do **not** manually bulk-upload `output/audio/`, and do **not** publish unrelated pre-existing local audio. Let `synthesize --upload-r2` upload only the helper shard's newly generated files, and let workflow `finalize` handle `publish --skip-audio`.
9. If `finalize` already failed waiting for the reserved helper manifest, rerun only the failed `finalize` job after the helper shard finishes uploading its manifest.

## Local-only fallback commands

```bash
uv sync --extra kokoro
export KELLBLOG_TTS_PROVIDER=kokoro
uv run kellblog-audio run-backfill
```

Or stepwise (recommended for long runs):

```bash
uv run kellblog-audio ingest          # ~15–30 min (network)
uv run kellblog-audio synthesize --pending   # ~1–2 days Kokoro on M-series Mac
uv run kellblog-audio publish --local-only   # keep the fallback fully local
```

## Resume

Every step is idempotent. Re-run after crash; completed rows are skipped unless `--force`.
Each episode is committed to the catalog only after its MP3 is fully written, so an interrupted run loses at most the in-progress episode.

## Speed (Chatterbox on Apple Silicon)

Measured on an M-series, 16 GB Mac:

| Config | Throughput | Notes |
|--------|-----------|-------|
| 1 CPU worker | ~7 it/s | original baseline |
| **1 MPS worker** (`KELLBLOG_CHATTERBOX_DEVICE=auto`) | **~13 it/s** | **recommended — ~2× faster, low RAM, laptop stays usable** |
| 2 CPU workers (`--shard 0/2`, `1/2`) | ~13 it/s aggregate | ~5.6 GB RAM, ~5 cores; only ties MPS while maxing the machine |
| 2 MPS workers | ~0.07 it/s | **do not use** — GPU thrashing, ~180× slower |
| 1 MPS + 1 CPU | ~7.6 it/s | worse — CPU worker starves MPS fallback ops |

A single MPS worker (the default with `auto`) is the best option on this hardware.
The model is loaded once and reused for the whole batch.

Parallel workers are available via `--shard i/N` (stable hash split, WAL-mode SQLite),
but on a single-GPU Mac they don't beat one MPS worker. They help only on multi-GPU /
CUDA machines, e.g. `synthesize --pending --shard 0/2` and `--shard 1/2` on two GPUs.

## Runtime (M-series Mac, CPU, Kokoro `am_michael`)

| Step | Estimate |
|------|----------|
| Ingest 778 URLs | 15–45 min |
| Synthesize ~117 hr audio | 1–2 days |
| Publish to R2 | minutes |

## Monitor

```bash
uv run kellblog-audio status
```

## Skip list

`audio-from-my-exit-five-cmo-leadership-retreat-presentation` is skipped (links to external audio). Add more via `KELLBLOG_SKIP_SLUGS=slug1,slug2`.
