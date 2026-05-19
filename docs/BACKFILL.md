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
