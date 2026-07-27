# Stalled Shard Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop distributed backfill from repeatedly restarting a GitHub-hosted shard that made no episode-level progress, while allowing a local MPS helper to complete reserved work.

**Architecture:** The workflow reads per-shard progress after a failed attempt and passes zero-progress GitHub shard indexes into the restart planner. The planner declines automatic redispatch for those shards and for runs that are waiting only for local-helper manifests. A local Mac process restores the existing baseline and writes the missing manifest using the same run ID.

**Tech Stack:** Python, Typer CLI, pytest, GitHub Actions, Cloudflare R2.

---

### Task 1: Detect stalled GitHub shards

**Files:**
- Modify: `src/kellblog_audio/distributed_backfill.py`
- Test: `tests/test_distributed_backfill.py`

- [ ] **Step 1: Write failing tests** for a missing non-helper shard with zero completed items and for a run missing only a local-helper manifest.
- [ ] **Step 2: Run the focused tests** and confirm the new expectations fail against the current restart planner.
- [ ] **Step 3: Add the smallest planner inputs and branches** needed to decline unsafe redispatches with actionable reasons.
- [ ] **Step 4: Re-run the focused tests** and confirm they pass.

### Task 2: Pass runtime progress into the workflow planner

**Files:**
- Modify: `.github/workflows/backfill-distributed.yml`
- Test: `tests/test_distributed_backfill.py`

- [ ] **Step 1: Read the run-scoped progress records** in `auto-restart` and identify missing GitHub shards with `processed_count == 0`.
- [ ] **Step 2: Pass the resulting indexes to `plan_backfill_auto_restart`.**
- [ ] **Step 3: Run the distributed-backfill test module** and validate workflow syntax by loading the YAML.

### Task 3: Document and execute the local MPS handoff

**Files:**
- Modify: `docs/BACKFILL.md`

- [ ] **Step 1: Document the GitHub six-hour constraint and the no-loop behavior.**
- [ ] **Step 2: Cancel the overlapping hosted attempt, restore the existing baseline, and run the missing `1/4` shard locally with `KELLBLOG_CHATTERBOX_DEVICE=auto`.**
- [ ] **Step 3: Verify the run-scoped progress and manifest state after the helper completes, then finalize the feed.**
