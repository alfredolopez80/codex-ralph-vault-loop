# Prompt 10 — structured progress hook integration

Status: PASS

## Scope

- `PostToolUse` recognizes only explicit structured test/build/lint/typecheck
  outcomes and delegates semantic state transitions to the canonical store.
- `Stop` verifies explicit progress completion against canonical state,
  provenance, approval/identity, material evidence, validation, and current
  Git/workspace identity.
- Approved planned checkpoints carry a bounded progress reference only;
  unplanned checkpoints preserve the generic compatibility shape.
- Normal wakeup no longer renders legacy implementation context. The legacy
  renderer remains behind an explicit compatibility/diagnostic flag.
- No hook registration switch, automatic derived-view export, or real-data
  migration is included.

## Evidence

- `tests/unit/test_progress_runtime_integration.py`: semantic validation
  transitions, repeated-success no-op, fail-to-pass, checkpoint reference,
  completion retry, corrupt/future state, and deleted-worktree handling.
- `tests/integration/test_progress_installed_dispatcher_e2e.py`: installed
  dispatcher PostToolUse validation and Stop completion against a temporary
  canonical repository; no progress-store Markdown/HTML output.
- `tests/unit/test_progress_hook_integration.py` and
  `tests/integration/test_implementation_notes_context.py`: lifecycle matrix,
  ambiguity, bounded context, and explicit legacy wakeup compatibility.
- Focused PostTool/Stop/dispatcher/config/legacy suite: PASS (78 tests).
- Hook lifecycle/config suite: PASS (86 tests); full repository suite: PASS
  (1114 tests, 5 subtests).
- Hook shell suite: `ALL_HOOK_TESTS_PASS`; Ralph memory-flow validation: PASS;
  project minimal gates: PASS (1 pass, 2 skips); global smoke and doctor: PASS.
- Local hook benchmark (`RALPH_HOOK_COST_ITERATIONS=5`): successful
  PostToolUse/Stop stdout remained 0 bytes, active roles remained one each,
  and the structured test path reported zero child processes. Representative
  p50/p95 values were 316.412/321.338 ms for medium-edit test (Luna) and
  87.060/93.000 ms for Stop allow (Luna). The aggregate report was
  4119.776/4257.709 ms; its full matrix is not a claim about provider usage.

## Runtime boundaries

The progress adapter is content-free at observability boundaries and forwards
writer-reported metrics. It never writes notes, HTML, consolidated views, or
archive snapshots. A semantic no-op does not append a progress event or replace
the state snapshot. The Stop adapter adds only a supported block finding; all
existing file-line, shaping, memory, advisor-observer, handoff, safety, and
continuation behavior remains owned by its existing policy modules.

## Risks and follow-up

- Legacy artifacts remain compatibility evidence until the explicit migration
  phase; normal wakeup and lifecycle hooks do not select them automatically.
- Hook registration remains unchanged by design. The installed dispatcher path
  is tested without changing global registration.
- Full hook/memory/doctor/benchmark gates are recorded above before the phase
  commit.
