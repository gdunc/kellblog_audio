#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# qa_rerun_watchdog.sh – resilient local MPS re-synth for a slug list
#
# Same failure modes as synth_watchdog.sh (idle sleep, MPS context loss,
# SIGHUP). Uses caffeinate tied to this process (-w $$), restarts on crash,
# and processes one slug at a time so a kill loses at most one episode.
#
# Run OUTSIDE Cursor (Terminal / tmux), e.g.:
#   cd /Users/grant.duncan/Documents/kellblog_audio
#   tmux new -s kellblog-qa
#   bash scripts/qa_rerun_watchdog.sh
#
# Optional env:
#   KELLBLOG_QA_RERUN_SLUGS=artifacts/repetition-rerun-remaining.txt
#   KELLBLOG_QA_RERUN_ELFYOURSELF=1   # QA elfyourself after slugs (default 1)
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/kellblog_qa_rerun_watchdog_$(date -u +%Y%m%dT%H%M%SZ).log"

SLUG_FILE="${KELLBLOG_QA_RERUN_SLUGS:-$REPO_DIR/artifacts/repetition-rerun-remaining.txt}"
if [ ! -s "$SLUG_FILE" ]; then
  SLUG_FILE="$REPO_DIR/artifacts/repetition-rerun-slugs.txt"
fi
QA_ELFYOURSELF="${KELLBLOG_QA_RERUN_ELFYOURSELF:-1}"
MAX_CONSECUTIVE_FAILURES="${KELLBLOG_QA_RERUN_MAX_FAILURES:-5}"

export KELLBLOG_TTS_PROVIDER="${KELLBLOG_TTS_PROVIDER:-chatterbox}"
export KELLBLOG_CHATTERBOX_DEVICE="${KELLBLOG_CHATTERBOX_DEVICE:-auto}"
export KELLBLOG_CHATTERBOX_EXAGGERATION="${KELLBLOG_CHATTERBOX_EXAGGERATION:-0.3}"
export KELLBLOG_CHATTERBOX_CFG_WEIGHT="${KELLBLOG_CHATTERBOX_CFG_WEIGHT:-0.45}"
export KELLBLOG_CHUNK_LOOP_RETRY="${KELLBLOG_CHUNK_LOOP_RETRY:-1}"
export KELLBLOG_CHUNK_LOOP_MAX_ATTEMPTS="${KELLBLOG_CHUNK_LOOP_MAX_ATTEMPTS:-3}"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_FILE"
}

CAFFEINATE_PID=""
if command -v caffeinate >/dev/null 2>&1; then
  # Tie assertions to this watchdog PID so they survive child exits.
  caffeinate -i -s -w $$ &
  CAFFEINATE_PID=$!
  log "caffeinate started (PID $CAFFEINATE_PID) – machine will stay awake"
else
  log "WARNING: caffeinate not found; machine may sleep and kill synthesis"
fi

cleanup() {
  if [ -n "$CAFFEINATE_PID" ]; then
    kill "$CAFFEINATE_PID" 2>/dev/null || true
    log "caffeinate stopped"
  fi
  log "Watchdog exiting."
}
trap cleanup EXIT INT TERM

slug_status() {
  local slug="$1"
  uv run python - <<PY
from kellblog_audio.catalog import Catalog
from kellblog_audio.config import CATALOG_PATH
post = Catalog(CATALOG_PATH).get("$slug")
print(post.audio_status if post else "missing")
PY
}

needs_synth() {
  local status
  status="$(slug_status "$1" | tr -d '[:space:]')"
  case "$status" in
    pending|stale|error|missing) return 0 ;;
    *) return 1 ;;
  esac
}

next_remaining_slug() {
  local slug
  while IFS= read -r slug || [ -n "${slug:-}" ]; do
    [ -z "${slug:-}" ] && continue
    if needs_synth "$slug"; then
      printf '%s\n' "$slug"
      return 0
    fi
  done < "$SLUG_FILE"
  return 1
}

count_remaining() {
  local slug n=0
  while IFS= read -r slug || [ -n "${slug:-}" ]; do
    [ -z "${slug:-}" ] && continue
    if needs_synth "$slug"; then
      n=$((n + 1))
    fi
  done < "$SLUG_FILE"
  printf '%s' "$n"
}

cd "$REPO_DIR"

log "QA rerun watchdog started (PID $$). Logging to: $LOG_FILE"
log "SLUG_FILE=$SLUG_FILE"
log "CHUNK_LOOP_RETRY=$KELLBLOG_CHUNK_LOOP_RETRY exaggeration=$KELLBLOG_CHATTERBOX_EXAGGERATION cfg=$KELLBLOG_CHATTERBOX_CFG_WEIGHT"

consecutive_failures=0

while true; do
  REMAINING="$(count_remaining)"
  if [ "${REMAINING}" -eq 0 ] 2>/dev/null; then
    log "All listed slugs are done (no pending/stale/error left)."
    break
  fi

  slug="$(next_remaining_slug)" || {
    log "All listed slugs are done (no pending/stale/error left)."
    break
  }

  log "─────────────────────────────────────────"
  log "Remaining: $REMAINING  next=$slug"
  log "Command: uv run kellblog-audio synthesize --all --slug $slug --force --upload-r2"

  START_TS=$(date +%s)
  uv run kellblog-audio synthesize --all --slug "$slug" --force --upload-r2 2>&1 | tee -a "$LOG_FILE"
  EXIT="${PIPESTATUS[0]}"
  ELAPSED=$(( $(date +%s) - START_TS ))

  if [ "$EXIT" -ne 0 ]; then
    consecutive_failures=$((consecutive_failures + 1))
    log "Synthesis exited with code $EXIT after ${ELAPSED}s."
    log "Consecutive failures: $consecutive_failures / $MAX_CONSECUTIVE_FAILURES"
    if [ "$consecutive_failures" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
      log "ERROR: Reached $MAX_CONSECUTIVE_FAILURES consecutive failures. Aborting."
      exit 1
    fi
    log "Sleeping 30s before restart to let MPS/memory settle…"
    sleep 30
    continue
  fi

  consecutive_failures=0
  log "Synthesis finished cleanly for $slug in ${ELAPSED}s."

  if needs_synth "$slug"; then
    log "WARNING: $slug still pending/stale/error after exit 0; will retry."
    sleep 10
    continue
  fi

  log "=== QA $slug ==="
  uv run kellblog-audio qa-audio --slug "$slug" 2>&1 | tee -a "$LOG_FILE" || true
done

if [ "$QA_ELFYOURSELF" = "1" ]; then
  log "=== QA elfyourselfs-7261-word-terms-of-service ==="
  uv run kellblog-audio qa-audio --slug elfyourselfs-7261-word-terms-of-service 2>&1 | tee -a "$LOG_FILE" || true
fi

log "QA rerun watchdog complete. ✓"
exit 0
