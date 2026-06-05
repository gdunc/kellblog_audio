# Kellblog Audio

Turn [Kellblog](https://www.kellblog.com/) posts into an AI-narrated podcast. One episode per blog post, organized by publication year (`itunes:season`), hosted on **Cloudflare R2**, distributed via RSS to **Apple Podcasts** and **Spotify for Creators**.

## Quick start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- `ffmpeg` and `ffprobe` (`brew install ffmpeg`)
- `espeak-ng` for Kokoro (`brew install espeak`)

### Install

```bash
cd kellblog_audio
uv sync --extra kokoro --extra dev
uv pip install -e .
```

All TTS engines for bake-off comparisons:

```bash
uv sync --extra compare   # kokoro + chatterbox + piper
uv run kellblog-audio providers
```

Individual extras: `--extra kokoro`, `--extra chatterbox`, `--extra piper`

### Phase 0 — TTS bake-off

```bash
# Ingest bake-off posts first
uv run kellblog-audio ingest --slug target-pipeline-coverage-is-not-the-inverse-of-win-rate

uv sync --extra compare   # kokoro + chatterbox + piper (StyleTTS2 uses isolated uv env)
uv run kellblog-audio bakeoff
uv run kellblog-audio bakeoff-serve   # http://localhost:8765/index.html
```

The bake-off generates **multiple voices per engine** (see `bakeoff_voices.py`). StyleTTS2 was previously a stub; it now runs via an isolated `uv run --with styletts2` subprocess because its dependencies conflict with Chatterbox.

Browse voices online (not your text): [Kokoro demo](https://huggingface.co/spaces/hexgrad/Kokoro-TTS), [Piper samples](https://rhasspy.github.io/piper-samples/), [Chatterbox](https://huggingface.co/ResembleAI/chatterbox), [StyleTTS2 demo](https://styletts2.github.io/).

Default production voice: **Kokoro** `am_michael`.

### Full backfill (local, ~1–2 days on M-series Mac with Kokoro)

```bash
uv run kellblog-audio run-backfill
# Or step by step:
uv run kellblog-audio ingest
uv run kellblog-audio synthesize --pending
uv run kellblog-audio publish --local-only
```

Resume is automatic: re-run the same command after any failure.

### Partial feed while synthesis runs

See [docs/WHILE_BACKFILL.md](docs/WHILE_BACKFILL.md) — build and validate `output/feeds/feed.xml` from completed episodes, then publish to R2 when credentials are ready.

### Cloudflare R2 setup

1. Create bucket `kellblog-audio` in Cloudflare R2.
2. Enable public access via custom domain `kellblog.thisisgrant.com` (see [docs/R2_CLOUDFLARE_SETUP.md](docs/R2_CLOUDFLARE_SETUP.md)).
3. Create API token with Object Read & Write.
4. Export:

```bash
export R2_ACCOUNT_ID=...
export R2_ACCESS_KEY_ID=...
export R2_SECRET_ACCESS_KEY=...
export R2_BUCKET=kellblog-audio
export KELLBLOG_AUDIO_PUBLIC_URL=https://kellblog.thisisgrant.com
```

5. Publish:

```bash
uv run kellblog-audio publish
```

### Podcast directory submission (one-time, manual)

Submit `https://kellblog.thisisgrant.com/feed.xml` to:

- [Apple Podcasts Connect](https://podcastsconnect.apple.com/)
- [Spotify for Creators](https://creators.spotify.com/) → Add show → RSS feed

Spotify and Apple poll the feed; new Kellblog posts are picked up automatically by the nightly GitHub Action.

### GitHub Action secrets

| Secret | Purpose |
|--------|---------|
| `R2_ACCOUNT_ID` | Cloudflare account |
| `R2_ACCESS_KEY_ID` | R2 API key |
| `R2_SECRET_ACCESS_KEY` | R2 API secret |
| `R2_BUCKET` | Bucket name |

Repository variable: `KELLBLOG_AUDIO_PUBLIC_URL` (optional).

## CLI commands

| Command | Description |
|---------|-------------|
| `kellblog-audio ingest` | Sync sitemap + fetch posts |
| `kellblog-audio synthesize --pending` | TTS for new/stale posts |
| `kellblog-audio publish` | Upload MP3s + feed to R2 |
| `kellblog-audio publish --local-only` | Write `output/feeds/feed.xml` only |
| `kellblog-audio status` | Pipeline counts |
| `kellblog-audio bakeoff` | Compare Kokoro vs Chatterbox samples |
| `kellblog-audio run-backfill` | ingest → synthesize → publish |
| `kellblog-audio backup-catalog` | Push SQLite to R2 |
| `kellblog-audio restore-catalog` | Pull latest SQLite from R2 |

## Episode metadata

- **Title:** blog post title (verbatim)
- **Description:** Ghost RSS excerpt + link to original + attribution footer
- **Intro (spoken):** “This is a Kellblog post from {date}, titled {title}.”
- **Outro (spoken):** “This audio version was created by Grant Duncan and AI, with permission from Dave.”
- **Show notes footer:** includes [thisisgrant.com](https://thisisgrant.com)

## Voice cloning later

Set `KELLBLOG_TTS_PROVIDER=chatterbox` and provide a reference WAV in config (see `tts.py`). Re-synthesize with `kellblog-audio synthesize --force`. No RSS schema changes.

## Hosting cost

Cloudflare R2: ~10–12 GB MP3 archive ≈ **$0–$0.20/month** (10 GB free tier, zero egress).

## Tests

```bash
uv run pytest
```

## License

Pipeline code: MIT. Respect Kellblog / Dave Kellogg content rights; this project is authorized by Dave.
