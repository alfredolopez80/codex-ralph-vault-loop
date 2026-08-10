# PR draft — implementation progress overhaul release candidate

## Title

`fix: make global Codex hook rollout parse-safe`

## Summary

This follow-up makes the merged implementation-progress overhaul safe to
install globally with the current Codex runtime. The canonical JSON/JSONL store
remains the single bounded source of truth; legacy HTML/index/consolidated
views are explicit migration/rollback outputs. In addition to the merged
hardening, this PR fixes the global hook budget serializer so Codex receives
integer `u64`-compatible values and rejects invalid numeric configuration
before publication.

The installer and smoke path now enforce the same numeric contract, with
regression coverage for both generated configuration and invalid float values.

## Review closure

- Repeated task-boundary signatures receive a unique content-free cache epoch
  before routing reinitialization, including identical concurrent boundaries.
- `active` and `reopened` plans remain discoverable through validation and Stop
  completion; completion requires a non-empty canonical all-pass validation map.
- Registration preflights the bounded manifest while holding the plan and
  manifest locks; stale manifest candidates cannot regress the event sequence.
- Direct `mypy`/`ruff`/`tsc`/`uv`/`npx` validation runners are recognized by the
  structured gate detector, independent of the generic tool heuristic.
- Rollback snapshots all targets, restores already-published targets after a
  failure, and rejects fixed-name outputs that overlap canonical plan sources.
- Tool labels are redacted and bounded before cost-ledger persistence; RED
  checkpoint rejection metrics reflect the actual bounded append.
- Terminal-business retention follows a monotonic claim sequence rather than
  lexical scope-key order. Malformed markers remain untouched for recovery.

## Exact candidate

| Item              | Value                                                                |
| ----------------- | -------------------------------------------------------------------- |
| Base / merge base | `bc60308ac04164ace84cfcba35df3efd1bb79446`                           |
| Fix commit        | `5346da911282517b2618403d911bf49d69cdb092`                           |
| Branch            | `codex/global-rollout-schema-fix`                                    |
| Worktree          | `/Users/alfredolopez/Documents/GitHub/codex-ralph-progress-overhaul` |
| Executor          | `gpt-5.6-luna/max` only                                              |

## Validation

- Full suite: `1143 passed, 5 subtests passed`.
- Hook/config focused suite: `88 passed`; budget/config regression suite:
  `16 passed`.
- Hook shell suite: `ALL_HOOK_TESTS_PASS`.
- Ralph memory-flow validation: `PASS` (30 memory unit, 2 integration, 6
  write-safety; ruff/mypy unavailable and explicitly skipped).
- Minimal gates: `failed=0, passed=1, skipped=2`.
- Isolated global install in a temporary `HOME`: `GLOBAL_INSTALL_DONE`.
- Isolated smoke: `GLOBAL_HOOKS_SMOKE_PASS`.
- Isolated doctor: `GLOBAL_DOCTOR_PASS warnings=1`; the only warning was the
  intentionally absent temporary global `config.toml`.
- Isolated real Codex session passed hook-config parsing and reached the API;
  it stopped with `401 Unauthorized` because the temporary HOME had no
  credentials. No real global config or MCP settings were loaded.
- `git diff --check` and Python compilation: `PASS`.
- Hook cost benchmark: `hook_cost_score=7079.227`,
  `hook_total_p50_ms=4219.227`, `hook_output_context_units=1430`.
- Local Luna/Max canary: `20/20 PASS`; feature/recovery p95 `0.066/0.068 ms`;
  model/worker/advisor/MCP/network calls `0/0/0/0/0`.
- Store transaction benchmark (20 samples): material p50/p95
  `14.883/22.858 ms`; unchanged retry p50/p95 `13.516/21.400 ms`; retry bytes
  `0`; provider calls `0`.

The Phase 0 aggregate comparison remains explicitly
`UNKNOWN/INCOMPATIBLE` because the baseline is schema 1 and the candidate is
schema 2. These local metrics are not provider, account, subscription, or
monetary-usage measurements.

## Migration, rollback, and privacy boundary

Migration/rollback proof uses deterministic temporary Git fixtures only:
source bytes and mtimes remain unchanged, reruns import zero duplicates,
journal/state survive rollback, global views retain unselected plans, injected
publication failure restores all prior targets, and canonical-source output
collisions block before publication. No real local `.ralph/plans` data was
migrated.

Progress maintenance is local-only with zero Terra/Sol/advisor/worker/MCP
allowance. Model fields are bounded provenance labels, not executor
attestation. RED bodies are rejected or redacted and never copied into reports,
ledgers, notes, prompts, or external routes. No real provider usage CSV/JSON was
found; optional `--usage` remains operator-supplied and `verified=false`.

## Residuals and approval boundary

- Provider/account/subscription usage is unknown by design; no savings claim is
  made.
- Whole-dispatcher comparison is schema-incompatible and scheduler-sensitive.
- Hash chains provide ordering/integrity evidence, not signatures against a
  local writer who can rewrite every byte.
- The real global installation remains rolled back until this branch is merged
  into `origin/main`; the pre-existing global `hooks.json` still contains the
  old floating-point budget values and is intentionally not modified by this
  PR branch.
- Real-user-data migration, recovery-mode migration, hook cutover, merge, and
  deployment require a separate explicit approval.

This is the prepared body for the follow-up PR. Push and PR creation are
authorized for this branch; approval, merge, and the guarded global rollout are
separate subsequent boundaries.
