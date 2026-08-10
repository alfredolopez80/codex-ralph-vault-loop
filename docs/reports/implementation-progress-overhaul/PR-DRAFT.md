# PR draft — implementation progress overhaul release candidate

## Title

`fix: harden implementation progress release candidate`

## Summary

This change set completes the local implementation-progress overhaul through a
Luna/Max release-candidate gate. It makes the JSON/JSONL store authoritative,
keeps context recovery cache-first and epoch-aware, and hardens canonical and
auxiliary runtime persistence against traversal, symlink/hardlink aliasing,
TOCTOU replacement, partial writes, unbounded input/output, and future-schema
downgrade. It also makes Stop fail closed for invalid or incomplete progress and
keeps legacy views behind explicit CLI/migration/rollback boundaries.

## Validation

- Full test suite: `1124 passed, 5 subtests`.
- Hook shell suite: `ALL_HOOK_TESTS_PASS`.
- Ralph memory-flow validation: PASS.
- Minimal gates: failed `0`, skipped `1` (security skip is expected in minimal mode).
- Global smoke/doctor: PASS against the pre-existing installed source marker;
  no global files were changed.
- Canary: 20/20 deterministic scenarios PASS, zero model/worker/advisor/MCP/
  network calls.
- Store benchmark: material/retry p50 `18.533/16.574 ms`, p95 `26.570/25.234 ms`, zero provider calls.
- Phase 0 aggregate comparison remains explicitly UNKNOWN/INCOMPATIBLE
  (schema 1 versus schema 2).

## Scope and residual risk

The migration and rollback commands are reversible, bounded, and explicit, but
real local plan data and hook registration remain deferred. Hash chains provide
local integrity evidence rather than signatures. Provider/subscription usage is
not observable, and the installed global source remains a separate checkout.

## Approval boundary

This PR is intentionally draft and is not approved for merge. Approval remains
required before any global install/switch, real-user-data migration,
recovery-mode migration, merge, or deployment. Push and PR creation were
explicitly authorized for this review preview.
