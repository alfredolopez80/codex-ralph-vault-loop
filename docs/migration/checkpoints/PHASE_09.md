# PHASE 09 - Objective Stop Dispatcher

Date: 2026-08-08
Repository: `codex-ralph-vault-loop`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_08.md` exists and ends with decision `PASS`.

## Scope

The eight production Stop commands are replaced by one
`.codex/hooks/stop_dispatch.py`. It parses one payload, scopes evidence to the
active project/session/task, evaluates objective gates, persists a bounded
handoff, and reserves at most one ordinary continuation plus one retry for a
new critical evidence fingerprint.

Phrase scans, absent route markers, stale or foreign state, and deferred review
are report-only. Project and global configuration register only the dispatcher.

## Safety

State is schema-versioned, TTL-bounded, locked, atomic, and quarantines corrupt
JSON. Operational write failures fail open. Output and persisted records hold
bounded codes, identifiers, and metrics only; heavy promotion remains outside
the Stop critical path behind a fast marker.

## Validation

- Unit plus effective-chain/lifecycle: `588 passed, 5 subtests passed`.
- Hook/config/global-install/Sol integration: `138 passed`.
- `.codex/tests/run-hook-tests.sh`: `ALL_HOOK_TESTS_PASS`.
- `scripts/validate-ralph-memory-flow.sh`: `PASS` (30 recall unit, 2 fake
  integration, 6 persistence-safety tests).
- Temporary-home install and smoke: `GLOBAL_HOOKS_SMOKE_PASS`; real global
  install intentionally not run, so real smoke/doctor report stale user-level
  configuration under the no-global-write constraint (`smoke`: missing
  `post_tool_dispatch`; `doctor`: three expected source/config failures).
- The final ten-iteration benchmark reports direct project Stop p50/p95 of
  `80.741/83.241 ms` for allow and `82.131/82.904 ms` for ordinary objective
  failure; global dispatch adds one known hook child process. No 00-baseline
  JSON was available in `/tmp`, so no baseline delta is claimed.

## Decision

PASS
