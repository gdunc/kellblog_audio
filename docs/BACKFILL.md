# Full archive backfill

~778 posts, ~117 hours of audio, ~8–12 GB MP3 at 128 kbps mono.

## Commands

```bash
uv sync --extra kokoro
export KELLBLOG_TTS_PROVIDER=kokoro
uv run kellblog-audio run-backfill
```

Or stepwise (recommended for long runs):

```bash
uv run kellblog-audio ingest          # ~15–30 min (network)
uv run kellblog-audio synthesize --pending   # ~1–2 days Kokoro on M-series Mac
uv run kellblog-audio publish         # upload to R2 when configured
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
