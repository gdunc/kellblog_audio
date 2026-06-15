#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# synth_watchdog.sh – keeps "kellblog-audio synthesize --pending" alive
#
# Root cause: macOS kills the process (memory pressure / MPS context loss /
# display sleep / SIGHUP on terminal disconnect) with no Python exception.
# This script detects the crash and restarts automatically, and uses
# `caffeinate` to prevent macOS idle sleep during the run.
#
# Usage (pick one):
#   # In a tmux/screen session (recommended):
#   bash scripts/synth_watchdog.sh
#
#   # Fully detached from the terminal:
#   nohup bash scripts/synth_watchdog.sh &
#   disown
#
# The watchdog exits cleanly when audio_pending reaches 0 or after
# MAX_CONSECUTIVE_FAILURES back-to-back crashes.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/kellblog_synth_watchdog_$(date -u +%Y%m%dT%H%M%SZ).log"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_FILE"
}

# ---------------------------------------------------------------------------
# caffeinate – prevent macOS idle/display sleep (requires no special perms)
# ---------------------------------------------------------------------------
CAFFEINATE_PID=""
if command -v caffeinate &>/dev/null; then
    # -i: prevent idle sleep  -s: prevent system sleep (works on AC power)
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

# ---------------------------------------------------------------------------
# Helper: count pending episodes via the CLI (avoids sqlite dependency)
# awk prints the first bare integer on the "audio pending" line.
# We avoid pipefail-related SIGPIPE issues by using a single awk pass.
# ---------------------------------------------------------------------------
pending_count() {
    local n
    n=$(uv run kellblog-audio status 2>/dev/null \
        | awk '/audio pending/ { for(i=1;i<=NF;i++) if ($i~/^[0-9]+$/) { print $i; exit } }')
    printf '%s' "${n:-0}"
}

# ---------------------------------------------------------------------------
# Main restart loop
# ---------------------------------------------------------------------------
MAX_CONSECUTIVE_FAILURES=5
consecutive_failures=0

cd "$REPO_DIR"

log "Watchdog started (PID $$). Logging to: $LOG_FILE"
log "MAX_CONSECUTIVE_FAILURES=$MAX_CONSECUTIVE_FAILURES"

while true; do
    PENDING="$(pending_count)"

    if [ "${PENDING}" -eq 0 ] 2>/dev/null; then
        log "All episodes synthesized (audio_pending=0). Watchdog done. ✓"
        exit 0
    fi

    log "─────────────────────────────────────────"
    log "Starting synthesis run  ($PENDING episodes pending)…"
    log "Command: uv run kellblog-audio synthesize --pending"

    START_TS=$(date +%s)

    # Run synthesis; EXIT captures the synthesize exit code even through tee.
    uv run kellblog-audio synthesize --pending 2>&1 | tee -a "$LOG_FILE"
    EXIT="${PIPESTATUS[0]}"

    ELAPSED=$(( $(date +%s) - START_TS ))

    if [ "$EXIT" -eq 0 ]; then
        log "Synthesis run finished cleanly (exit 0) in ${ELAPSED}s."
        consecutive_failures=0
        # Loop: check if a concurrent ingest added more pending episodes.
        continue
    fi

    consecutive_failures=$(( consecutive_failures + 1 ))
    log "Synthesis exited with code $EXIT after ${ELAPSED}s."
    log "Consecutive failures: $consecutive_failures / $MAX_CONSECUTIVE_FAILURES"

    if [ "$consecutive_failures" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
        log "ERROR: Reached $MAX_CONSECUTIVE_FAILURES consecutive failures. Aborting."
        exit 1
    fi

    SLEEP_SECS=30
    log "Sleeping ${SLEEP_SECS}s before restart to let MPS/memory settle…"
    sleep "$SLEEP_SECS"
done
