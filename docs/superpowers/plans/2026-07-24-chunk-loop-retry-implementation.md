# Chunk Loop Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development (required). Prefer superpowers:subagent-driven-development or superpowers:executing-plans for task execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect Chatterbox phrase loops per TTS chunk and retry with calmer params; stop auto-queuing short episodes that fail coverage/tail only.

**Architecture:** Add a shared n-gram loop helper in `qa.py`, wrap chunk synthesis in `tts.py` with Whisper-backed retry profiles, and gate `queue_audio_rerun` for short coverage/tail-only failures. Then re-queue the nine known repetition failures for a local MPS pass.

**Tech Stack:** Python 3.11, pytest, Whisper CLI, Chatterbox

---

## File map

- Modify: `src/kellblog_audio/qa.py`
- Modify: `src/kellblog_audio/tts.py`
- Modify: `src/kellblog_audio/config.py`
- Modify: `src/kellblog_audio/synthesize.py` (only if needed to pass retry flags / report auto_rerun)
- Modify: `src/kellblog_audio/cli.py` (`qa-audio --rerun-failed` respects `auto_rerun`)
- Test: `tests/test_audio_qa.py` (or new `tests/test_chunk_loop_retry.py`)
- Test: `tests/test_tts_chunk.py`

---

### Task 1: Loop helper + short-episode auto_rerun policy

**Files:**
- Modify: `src/kellblog_audio/qa.py`
- Modify: `src/kellblog_audio/config.py`
- Test: `tests/test_audio_qa.py`

- [ ] **Step 1: Write failing tests**

```python
from kellblog_audio.qa import chunk_has_loop, analyze_transcript

def test_chunk_has_loop_detects_repeated_trigrams():
    words = (["the", "rule", "of"] * 20)
    assert chunk_has_loop(" ".join(words)) is True

def test_chunk_has_loop_clean_text_is_false():
    assert chunk_has_loop("hello world this is a normal sentence about saas") is False

def test_analyze_transcript_short_coverage_fail_disables_auto_rerun():
    # very short source; transcript misses some words → coverage fail only
    result = analyze_transcript(
        "One two three four five six seven eight",
        "One two three four five",
        duration_sec=5,
        intro_text="",
        outro_text="",
    )
    assert result.passed is False
    assert result.auto_rerun is False
```

- [ ] **Step 2: Run tests — expect FAIL** (`chunk_has_loop` / `auto_rerun` missing)

- [ ] **Step 3: Implement**
  - `SHORT_SOURCE_WORDS` in config (default 80)
  - `chunk_has_loop(text, *, max_repeated=MAX_REPEATED_THREE_GRAM) -> bool`
  - Add `auto_rerun: bool` to `TranscriptQAResult` (default True when failed for repetition/wpm; False when short + coverage/tail only)
  - Update `analyze_transcript` accordingly

- [ ] **Step 4: Run tests — expect PASS**

---

### Task 2: Chunk synthesize with retry

**Files:**
- Modify: `src/kellblog_audio/tts.py`
- Modify: `src/kellblog_audio/config.py`
- Test: `tests/test_tts_chunk.py`

- [ ] **Step 1: Write failing test** with a fake provider that loops on attempt 1 and succeeds on attempt 2; monkeypatch Whisper/transcribe to return looping then clean text.

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `synthesize_chunk_with_loop_retry`** used by `synthesize_to_wav`:
  - Attempt profiles: `(exaggeration, cfg_weight)` list
  - On ChatterboxProvider, temporarily set attrs for attempts 2+
  - Call `transcribe_audio` on the part wav (injectable for tests)
  - Env: `KELLBLOG_CHUNK_LOOP_RETRY` (default on), `KELLBLOG_CHUNK_LOOP_MAX_ATTEMPTS=3`

- [ ] **Step 4: Run — expect PASS**

---

### Task 3: Wire QA CLI / synthesize queue to `auto_rerun`

**Files:**
- Modify: `src/kellblog_audio/cli.py`
- Modify: `src/kellblog_audio/synthesize.py` if it queues on QA fail
- Test: `tests/test_cli_qa.py` or `tests/test_synthesize_quality.py`

- [ ] **Step 1: Failing test** — `--rerun-failed` does not queue when `auto_rerun=False`
- [ ] **Step 2: Implement minimal gate**
- [ ] **Step 3: Tests pass**

---

### Task 4: Re-run the 9 repetition failures locally

**Do not interrupt** in-progress `elfyourselfs` shard 17 synth.

Slugs:

1. `an-update-on-the-saas-rule-of-40`
2. `cac-payback-period-the-most-misunderstood-saas-metric`
3. `i-dont-want-to-talk-to-you-anymore`
4. `kellblog-predictions-for-2026`
5. `my-final-verdict-on-multi-year-pre-paid-deals`
6. `rule-of-40-glideslope-planning`
7. `the-re-emergence-of-product-line-marketing`
8. `the-rule-of-40-down-but-not-out`
9. `the-saas-rule-of-40`

- [ ] Mark those 9 stale via `queue_audio_rerun` / catalog update
- [ ] After shard 17 finishes (or in a separate process once GPU free):  
  `KELLBLOG_CHATTERBOX_EXAGGERATION=0.3 KELLBLOG_CHATTERBOX_DEVICE=auto KELLBLOG_CHUNK_LOOP_RETRY=1 uv run kellblog-audio synthesize --pending --upload-r2`
- [ ] QA each of the 9; report pass/fail counts

---

### Task 5: Verification

- [ ] `uv run pytest tests/test_audio_qa.py tests/test_tts_chunk.py tests/test_cli_qa.py -q`
- [ ] Confirm short coverage fails no longer increment `queued-for-rerun` under `--rerun-failed`
