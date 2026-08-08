# PHASE 11 - Incremental SessionStart and Compaction

> Historical note: the earlier checkpoint with this number covered the
> evaluation spine and remains recoverable in git history. This file records
> the active runtime-optimization phase.

Date: 2026-08-08
Repository: `codex-ralph-vault-loop`

## Previous checkpoint

`docs/migration/checkpoints/PHASE_10.md` exists and is marked `PASS`.

## First-principles decision

The irreducible SessionStart contract is scoped continuity, not maintenance.
The wakeup subprocess was an assumption rather than a requirement; local
metadata, fingerprints, and bounded files are sufficient. Startup, resume,
clear, and compact therefore use one reducer with source-specific policies.

## Implementation

- `session_start_dispatch.py` reads payload model, source, profile, active
  workspace metadata, checkpoint, handoff, selected memory IDs, and safe route
  metadata once.
- `session_start_wakeup.py` remains a compatibility wrapper and no longer
  imports or launches the wakeup script.
- `runtime_profile.py` resolves payload model first, then explicit environment,
  then repository config; unknown values select `conservative_unknown`.
- `session_context_cache.py` stores only schema-versioned hashes, safe IDs,
  scope metadata, timestamps, and statuses with atomic writes, locking, TTL,
  bounded entries, corruption quarantine, and fail-open behavior.
- The fast Git resolver reads worktree `HEAD`, refs, `commondir`, and local
  config without spawning a child process.

## Source policies and budgets

- `startup`: scoped project/branch/HEAD orientation and useful task,
  validation, or handoff deltas.
- `resume`: empty for an unchanged fingerprint; otherwise only changed fields.
- `clear`: clears ephemeral session state without deleting durable memory.
- `compact`: objective, phase, active files, pending validation, and selected
  memory IDs only.
- UTF-8 byte budgets: LUNA `1500/2200` soft/hard, SOL `500/800`, unknown
  `1500/2200` conservative hard limit.
- `child_process_count=0` for all fast-path sources; outer interpreter startup
  is measured separately.

## Safety and scope

Foreign branch/workspace/HEAD artifacts are ignored. Stale and corrupt
artifacts are marked or skipped, never treated as authority. The cache does
not contain raw prompt, transcript, memory, vault, or sensitive bodies.
Maintenance remains enqueue-only; dream, promotion, vault review, and the
wakeup subprocess stay outside SessionStart.

## Validation

- New profile and source matrix tests pass, including LUNA/SOL/unknown,
  startup/resume/clear/compact, cache hits, deltas, corruption, stale and
  foreign scope, UTF-8 limits, RED exclusion, and no heavy child process.
- Existing lifecycle, worktree-isolation, vault-review, config-lockstep, and
  benchmark tests remain green.
- The benchmark now emits a `session_start` section with 12 source/profile
  cases and reports `child_process_count=0` for every case.
- Five-iteration local benchmark (`schema_version=2`,
  `subscription_usage_measured=false`) measured outer-process p95 values of
  `51.2-60.5 ms` across the 12 cases (startup, resume, clear, compact for
  LUNA, SOL, and conservative unknown); resume/clear output was `0` bytes,
  compact output was `93-114` bytes, and startup output was `135-156` bytes.
  The comparison command correctly classified the existing malformed
  `/tmp/ralph-hook-baseline.json` as `cambio no comparable` rather than
  fabricating a delta.

## Open limitations

- SessionStart still enqueues the deferred maintenance descriptor; scheduling
  the explicit runner remains an operator/automation responsibility.
- The platform contract for a dedicated PostCompact hook is not verified, so
  compact restoration is handled by the SessionStart source reducer.
- A standalone Phase 00 baseline must be regenerated before claiming a direct
  baseline delta.

Decision: PASS
