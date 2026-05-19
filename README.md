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

Optional second TTS engine for bake-off / voice cloning:

```bash
uv sync --extra chatterbox
```

### Phase 0 — TTS bake-off

```bash
# Ingest bake-off posts first
uv run kellblog-audio ingest --slug taxonomies-and-tags
uv run kellblog-audio ingest --slug target-pipeline-coverage-is-not-the-inverse-of-win-rate
uv run kellblog-audio ingest --slug a-diamond-in-the-rough-startup-founder-survival-guide-by-david-politis

uv run kellblog-audio bakeoff
# Listen under output/bakeoff/ — then set provider:
export KELLBLOG_TTS_PROVIDER=kokoro   # or chatterbox
```

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

### Cloudflare R2 setup

1. Create bucket `kellblog-audio` in Cloudflare R2.
2. Enable public access via custom domain `audio.kellblog.com`.
3. Create API token with Object Read & Write.
4. Export:

```bash
export R2_ACCOUNT_ID=...
export R2_ACCESS_KEY_ID=...
export R2_SECRET_ACCESS_KEY=...
export R2_BUCKET=kellblog-audio
export KELLBLOG_AUDIO_PUBLIC_URL=https://audio.kellblog.com
```

5. Publish:

```bash
uv run kellblog-audio publish
```

### Podcast directory submission (one-time, manual)

Submit `https://audio.kellblog.com/feed.xml` to:

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
