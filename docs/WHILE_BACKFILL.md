# While synthesis is still running

You can complete most launch steps with only the episodes already marked `done` in the catalog.
Re-run publish after more batches finish; the feed always includes every `done` + `skip` post.

## Ready now (no R2 required)

```bash
uv run kellblog-audio status
uv run kellblog-audio publish --local-only
```

Output: `output/feeds/feed.xml` — includes all synthesized episodes so far.

Validate before directory submit:

- https://castfeedvalidator.com/ (upload `output/feeds/feed.xml`)
- https://podba.se/validate/

## When R2 is configured

Add credentials to `.env` (see `.env.example`), then:

```bash
# Upload MP3s for all done episodes + refresh feed on R2
uv run kellblog-audio publish

# Feed-only update after more local synthesis (skip re-uploading audio)
uv run kellblog-audio publish --skip-audio

# Snapshot catalog for GitHub Action / other machines
uv run kellblog-audio backup-catalog
```

Public feed URL: `https://kellblog.thisisgrant.com/feed.xml` (set `KELLBLOG_AUDIO_PUBLIC_URL`). Setup: [R2_CLOUDFLARE_SETUP.md](./R2_CLOUDFLARE_SETUP.md).

## One-time directory submit

After R2 feed is live, follow [DIRECTORY_SUBMIT.md](./DIRECTORY_SUBMIT.md).

You can submit with a partial catalog (340+ episodes) and Apple/Spotify will pick up new items as you re-run `publish`.

## Nightly automation

`.github/workflows/sync-podcast.yml` runs ingest → synthesize pending → publish → backup catalog.
Configure GitHub secrets from `.env.example` before enabling.

## Do not run in parallel with local synthesis

`publish` only reads the catalog and writes `feed.xml` (or uploads). Safe while `synthesize --pending` runs, but avoid `backup-catalog` / `restore-catalog` on the same SQLite file from two machines at once.
