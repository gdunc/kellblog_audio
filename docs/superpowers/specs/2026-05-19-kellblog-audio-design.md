# Kellblog Audio — Design Spec

**Date:** 2026-05-19  
**Status:** Implemented in `kellblog_audio` package

## Goal

Turn [Kellblog](https://www.kellblog.com/) into an AI-narrated podcast with year-based seasons, hosted on Cloudflare R2, distributed via RSS to Apple Podcasts and Spotify for Creators.

## Architecture

- **Ingest:** `sitemap-posts.xml` → SQLite catalog → fetch HTML → normalize text
- **Synthesize:** Kokoro (default) or Chatterbox → intro + body + outro → MP3
- **Publish:** Single `feed.xml` with `itunes:season` tags → R2 (`audio.kellblog.com`)

## TTS bake-off (Phase 0)

Default production engine: **Kokoro** (`am_michael`). Alternatives: **Chatterbox** (MIT, voice cloning). StyleTTS2 not bundled.

Run: `kellblog-audio bakeoff` after ingesting bake-off slugs.

## Attribution

- Spoken outro: permission from Dave (no URL in audio)
- RSS footer: includes [thisisgrant.com](https://thisisgrant.com)

## Voice cloning later

Swap `KELLBLOG_TTS_PROVIDER=chatterbox` and provide a reference WAV; re-run `synthesize --force` for desired slugs. No feed schema changes.
