# Archive QA Sweep — Design Spec
**Date:** 2026-07-15  
**Status:** Draft for review

## Goal
Add a local, resumable way to generate missing Whisper QA artifacts for all completed archive episodes, using the existing QA pipeline and without changing the current review-page or publish flow.

## Requirements
- Reuse the existing `qa_post_audio()` logic so QA artifacts remain `output/transcribe/qa/<slug>.qa.json`.
- Support a full sweep of `audio_status=done` episodes that do not yet have a QA artifact.
- Keep the existing one-off `qa-audio --slug <slug>` flow.
- Make interrupted runs resumable without extra bookkeeping.
- Allow optional queueing of genuine QA failures for regeneration.
- Preserve current review-page compatibility.

## Non-goals
- Building a distributed GitHub Actions QA workflow.
- Automatically regenerating all episodes flagged for manual audit.
- Changing the Whisper scoring thresholds or review-page concern thresholds.
- Reworking synthesis, publish, or R2 storage behavior.

## Problem Summary
The archive currently has many completed MP3s but only partial Whisper QA coverage. The review page treats missing QA artifacts as a concern, which makes the page noisy and reduces confidence in the archive. The missing artifacts are a coverage gap, not necessarily an audio-quality failure.

The existing `qa-audio` command is built for spot checks, not an archive sweep. It defaults to a small batch and does not have a mode that directly targets completed episodes missing QA artifacts.

## Design Overview
Extend the existing `qa-audio` CLI command so it can run in three modes:

1. `--slug <slug>`: QA exactly one episode.
2. Default mode: QA a small spot-check batch of completed episodes, preserving current behavior.
3. `--missing-only`: QA completed episodes that do not yet have a `*.qa.json` artifact, optionally limited for chunked runs.

The command remains local and sequential. Each successful QA result writes its artifact immediately. Because the missing-only selector is based on the presence of those artifacts, an interrupted run can be resumed by rerunning the same command.

## CLI Changes
Enhance `kellblog-audio qa-audio` with:

- `--missing-only`
  - Select only `audio_status=done` episodes whose `output/transcribe/qa/<slug>.qa.json` file is missing.
  - Mutually exclusive with `--slug`.

- `--limit <N>`
  - Applies after selection/filtering.
  - In `--missing-only` mode, omission means "run all missing episodes."
  - In default mode, preserve the current small-batch behavior by using a default of 5 when the user does not provide a limit.

- `--rerun-failed`
  - Keep existing semantics: if an episode completes QA and `passed` is false, mark it stale for regeneration.
  - Do not queue episodes that hit an operational error such as missing local audio or missing Whisper dependencies.

### Intended command examples
```bash
uv run kellblog-audio qa-audio --slug some-episode
uv run kellblog-audio qa-audio
uv run kellblog-audio qa-audio --missing-only --limit 100
uv run kellblog-audio qa-audio --missing-only
```

## Selection Rules
- If `--slug` is provided, QA only that slug.
- Else if `--missing-only` is provided, select done episodes whose QA artifact is absent.
- Else, select completed episodes for a small spot check.

Selection order should follow the existing catalog ordering used by `list_by_filter(audio_status="done")` so the new mode remains predictable and easy to resume.

## Runtime Behavior
### Preflight
Before processing the batch, validate that:
- the Whisper CLI is available
- the configured Whisper model path exists

If either check fails, abort the command immediately with a clear error message because the whole run is blocked.

### Per-episode processing
For each selected episode:
- run `qa_post_audio()`
- print a pass/fail line with the existing reason and metrics
- if `--rerun-failed` is set and the QA result failed, queue it for regeneration

### Artifact handling
Successful QA runs should continue writing:
- transcript text output
- transcript JSON output
- `*.qa.json` result files

to the existing `output/transcribe/qa/` directory. No new artifact location is introduced.

## Failure Handling
Two failure classes should be treated differently:

### Batch-blocking failures
- Whisper CLI not installed
- Whisper model file missing

These should fail fast before iterating the batch.

### Per-episode operational failures
- local MP3 missing
- unexpected transcription exception
- malformed post data

These should be logged, counted separately, and the sweep should continue with the next episode. They are not treated as QA failures and must not be queued by `--rerun-failed`.

## Summary Output
At the end of the run, print a compact summary with:
- selected
- checked
- passed
- failed
- errored
- queued-for-rerun

This gives enough signal to decide whether a follow-up regeneration pass is warranted.

## Verification Plan
Verify the implementation with short local checks before a full archive run:

1. Run `uv run kellblog-audio qa-audio --missing-only --limit 1`.
2. Confirm exactly one new `output/transcribe/qa/<slug>.qa.json` file appears.
3. Re-run the same command and confirm it advances to the next missing episode.
4. Run `uv run kellblog-audio qa-stats` before and after to confirm:
   - `qa artifacts` increases
   - `done missing qa` decreases
5. Confirm the review page still reads the artifacts without code changes.

## Operator Flow
For the archive sweep:

```bash
uv run kellblog-audio qa-audio --missing-only --limit 1
uv run kellblog-audio qa-stats
uv run kellblog-audio qa-audio --missing-only
uv run kellblog-audio qa-stats
```

If the sweep reveals real QA failures, decide separately whether to:
- rerun failed episodes with `--rerun-failed`
- inspect failures manually first

## Success Criteria
- The command can sweep all missing-QA completed episodes locally.
- The sweep is resumable by rerunning `qa-audio --missing-only`.
- New QA artifacts land where the existing review page already expects them.
- Operational errors do not stop the whole sweep.
- Genuine QA failures can be optionally queued for regeneration.
