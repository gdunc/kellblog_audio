# Chunk Loop Retry + Short-Episode QA Policy — Design Spec

**Date:** 2026-07-24  
**Status:** Approved (via “proceed with those next steps”)

## Goal

Reduce Chatterbox QA failures on archive re-synthesis by (1) catching phrase loops at chunk time and retrying, and (2) not auto-rerunning short/slide episodes that fail coverage/tail mostly due to Whisper brittleness.

## Problem (observed on 19-episode QA batch)

- **9 failures:** repetition loops (`max_repeated_three_gram` > 12) on longer prose; coverage usually still ≥92%.
- **~8–9 failures:** coverage/tail on short or slide/jargon posts (often &lt;400 words). Re-synth alone rarely helps.

## Requirements

1. After synthesizing each TTS chunk WAV, detect excessive 3-gram repetition via a short Whisper transcript of that chunk.
2. If the chunk fails the loop gate, discard it and re-synthesize with calmer Chatterbox params (up to N attempts).
3. Keep episode-level QA thresholds unchanged for normal episodes.
4. For short source text (`source_words < SHORT_SOURCE_WORDS`), do **not** auto-queue coverage/tail-only failures for regeneration; still write the QA artifact and report the result.
5. Re-queue only the 9 known repetition failures for a local re-synth pass using the new chunk-retry path and calmer defaults.

## Non-goals

- Changing review-page soft thresholds (`MIN_REVIEW_*`).
- Building a distributed Whisper QA workflow.
- Softening the hard repetition threshold for full episodes.
- Splitting a single episode across shards.

## Design

### A. Chunk loop gate (`tts.py` + `qa.py`)

- Reuse `_max_repeated_ngram` / `MAX_REPEATED_THREE_GRAM` from `qa.py` (or a shared helper).
- New helper: `chunk_has_loop(transcript_text, *, max_repeated=MAX_REPEATED_THREE_GRAM) -> bool`.
- New path in `synthesize_to_wav` / chunk loop:
  1. `provider.synthesize_chunk(text, part_wav)`
  2. If loop-retry enabled (default on for Chatterbox): Whisper-transcribe `part_wav`, check loop gate.
  3. On fail: delete part, retry with next param profile.
  4. After max attempts, keep the last attempt (or raise — **prefer keep last + log warning** so a long episode still finishes).

**Retry profiles (in order):**

| Attempt | exaggeration | cfg_weight |
|--------:|-------------:|-----------:|
| 1 | current / 0.4 | current / 0.5 |
| 2 | 0.3 | 0.45 |
| 3 | 0.25 | 0.4 |

Config knobs:

- `KELLBLOG_CHUNK_LOOP_RETRY` = `0` (default, keeps GHA fast) / `1` to enable
- `KELLBLOG_CHUNK_LOOP_MAX_ATTEMPTS` = `3`
- Optional: `KELLBLOG_CHATTERBOX_MAX_CHUNK_CHARS` default stays `600` for now; document trying `400` if loops persist.

### B. Short-episode QA policy (`qa.py` / `queue_audio_rerun` callers)

- `SHORT_SOURCE_WORDS = 80` (config/env overrideable).
- When analyzing transcript: if `source_words < SHORT_SOURCE_WORDS` and the **only** failures are coverage and/or tail (no repetition, no wpm), treat as `passed=False` for reporting **but** add `auto_rerun=False` (or equivalent) so `--rerun-failed` / synthesize QA halt do not queue it.
- Repetition failures on short posts still queue for rerun.

### C. Operator re-run of the 9 repetition failures

After code lands, locally:

1. Mark the 9 repetition slugs `stale` (if not already).
2. Synthesize with `KELLBLOG_CHATTERBOX_DEVICE=auto`, chunk loop retry on, calmer first-attempt exaggeration `0.3`.
3. QA each; only re-queue if still failing **repetition**.

## Success criteria

- Unit tests cover: loop detection helper; chunk retry tries alternate params; short-episode coverage fail does not queue rerun.
- Re-running the 9 repetition episodes produces fewer than 9 repetition failures (target: ≤3 remaining, ideally 0).
- Short coverage fails remain visible in `qa-stats` / review page but are not blindly re-synthesized.

## Risks

- Whisper-per-chunk slows synthesis (acceptable for quality-critical reruns; disable via env for bulk backfill if needed).
- Keeping last failed chunk still allows some loops through — logged so operators can spot them.
