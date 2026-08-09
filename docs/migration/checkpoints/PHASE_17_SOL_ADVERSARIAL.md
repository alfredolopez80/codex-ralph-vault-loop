# Phase 17 — SOL adversarial review

Status: **PASS**

Date: 2026-08-09

Baseline: `4784a55dd2b33e874ff8e615c6afe1488a8402dc`

Reviewed pre-fix candidate: `7543e206b7cf25d114b2f0743fe40560586f5ffb`

## Scope

The complete optimization diff was reviewed independently against the
baseline across security, hook contracts, correctness, memory, performance,
context economy, and compatibility. The read-only first pass was frozen before
edits. Only validated high and medium findings were corrected; each correction
has focused regression evidence.

Detailed evidence: [17-sol-adversarial-review.md](../../reports/runtime-optimization-v2/17-sol-adversarial-review.md).

## Finding outcome

- First pass: 0 critical, 8 high, 13 medium, 4 low, 6 false positives.
- Third pass: 0 critical open, 0 high open, 0 medium open.
- Four low observations are accepted and documented in the report.
- No opportunistic feature or broad refactor was added.

## Final validation

| Check                                                         | Result                                                                        |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q` | `992 passed, 5 subtests passed`                                               |
| Focused Stop/state regression                                 | `29 passed`                                                                   |
| `bash .codex/tests/run-hook-tests.sh`                         | `ALL_HOOK_TESTS_PASS`                                                         |
| `bash scripts/setup/doctor.sh`                                | `DOCTOR_PASS`                                                                 |
| Runtime structural gate                                       | PASS; candidate errors `[]`; 25 baseline handlers to 7 candidate handlers     |
| `python3 scripts/gates/run-gates.py --minimal`                | `1 passed, 2 skipped, 0 failed` using a temporary report directory            |
| `python3 scripts/evals/coding_model_eval.py --mode mock`      | score `0.9905`; route correctness `1.0`; unsafe-externalization incidents `0` |
| `bash scripts/validate-ralph-memory-flow.sh`                  | PASS                                                                          |
| Seven-iteration benchmark hard checks                         | PASS; `subscription_usage_measured=false`                                     |

The actual installed global smoke/doctor remains red because the installed
stable checkout does not contain the new dispatcher files. This is an expected
activation mismatch, not a candidate source failure: Phase 17 explicitly did
not install or modify user-global configuration. A temporary-HOME install,
doctor, and smoke integration path passed.

## Residual risk and next boundary

- Known child-process metrics are attribution, not full process-tree tracing.
- Inactive wrappers remain for compatibility and should be removed only in a
  separate migration phase.
- The one-iteration versus seven-iteration p95 comparison produced soft noise
  warnings; structural counts and absolute targets remain green.
- Repository-local/isolated canary: **GO**.
- Machine-wide canary: **GATED** until an explicitly authorized installation
  is followed by green global smoke and doctor checks.

No Phase 18 work was started.
