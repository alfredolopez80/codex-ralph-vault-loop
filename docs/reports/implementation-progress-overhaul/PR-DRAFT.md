# PR draft — implementation progress overhaul release candidate

## Title

`fix: harden implementation progress release candidate`

## Summary

This draft closes the validated Codex review findings against the
implementation-progress overhaul. The canonical JSON/JSONL store remains the
single bounded source of truth; legacy HTML/index/consolidated views are
explicit migration/rollback outputs. The hardening covers repeated task
boundaries, reopened-plan lifecycle discovery, manifest ordering/capacity,
canonical validation evidence, rollback restoration/source collisions, RED
tool-label accounting, terminal-claim recency, direct validation runners, and
truthful persistence metrics.

## Review closure

- Repeated task-boundary signatures discard the prior content-free claim before
  routing reinitialization.
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

| Item                            | Value                                                                |
| ------------------------------- | -------------------------------------------------------------------- |
| Base / merge base               | `92255e7d28a3bc84a005951957c953301ba40d7d`                           |
| Implementation hardening commit | `79aebb1`                                                            |
| Branch                          | `codex/implementation-progress-overhaul`                             |
| Worktree                        | `/Users/alfredolopez/Documents/GitHub/codex-ralph-progress-overhaul` |
| Executor                        | `gpt-5.6-luna/max` only                                              |

## Validation

- Full suite: `1139 passed, 5 subtests passed`.
- Focused migration/store/context/model-provenance/routing/no-op/concurrency/
  installed-dispatcher suites: `155 passed`.
- Review-hardening focused suite: `133 passed`.
- Hook shell suite: `ALL_HOOK_TESTS_PASS`.
- Ralph memory-flow validation: `PASS` (30 memory unit, 2 integration, 6
  write-safety; ruff/mypy unavailable and explicitly skipped).
- Minimal gates: `failed=0, passed=1, skipped=2`.
- Global smoke/doctor: `PASS`, warnings `0`; both observed the pre-existing
  stable source marker in `codex-ralph-vault-loop`, and no global files were
  changed.
- `git diff --check` and Python compilation: `PASS`.
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
- Global installed source remains the separate vault-loop checkout; this branch
  was not globally installed or switched on.
- Real-user-data migration, recovery-mode migration, hook cutover, merge, and
  deployment require a separate explicit approval.

This is a prepared draft for review. Push is authorized and will be performed
after the local docs update; no PR approval or merge is implied.
