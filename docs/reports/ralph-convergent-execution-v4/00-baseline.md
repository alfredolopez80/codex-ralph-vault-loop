# Ralph Convergent Execution v4 — T0 Baseline

Status: `baseline-captured-and-starting-gates-repaired`

## Starting identity

- Branch: `codex/ralph-convergent-execution-v4`
- HEAD: `78a314b47e6a1017b6d369358fda4c6c28450e06`
- Local `origin/main`: `78a314b47e6a1017b6d369358fda4c6c28450e06`
- Direct remote lookup: unavailable in this sandbox because DNS could not resolve `github.com`; the local remote-tracking ref was verified.
- Approved plan digest: `sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1`
- Policy source hash: `sha256:aa7847050dad0821c83f456b31a42efa0d6eea8989b22b33ecc6edb2c26adbef`

## Source reconciliation

The standalone v4 master, policy, README integration proposal, and visual
index match their ZIP members byte-for-byte. The v4 master and policy are
authoritative. Historical v3 sections are retained only as adversarial design
history. The microsite is excluded from implementation.

## Baseline commands

| Command                                                                                                                                      | Result                                                                                                                                                          |
| -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_hook_config_lockstep.py tests/integration/test_hooks_basic.py -q` | 87 passed                                                                                                                                                       |
| `bash .codex/tests/run-hook-tests.sh`                                                                                                        | Initial fixture coupling exposed a false progress association; after explicit fixture-plan isolation: `ALL_HOOK_TESTS_PASS`                                     |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit -q --maxfail=1`                                                               | Initial deleted-worktree identity/corrupt-state contract exposed a baseline defect; the bounded identity-preserving fix now passes the focused regression tests |
| `python3 scripts/gates/run-gates.py --minimal`                                                                                               | Captured during baseline; no failure output                                                                                                                     |
| `git diff --check`                                                                                                                           | pass                                                                                                                                                            |

The two initial failures were retained as starting evidence and repaired with
bounded, contract-preserving changes: explicit missing-worktree identity is
preserved for Stop validation, and hook fixtures cannot borrow the active
implementation plan. They are not counted as v4 regressions. The full unit
and hook suites remain required before rollout.

## Required baseline measurements

The paired scenario manifest is stored beside this report. The candidate and
baseline must use the same 24 scenarios, same repository snapshot, same
environment, and the same measurement schema. Subscription credit usage is
`UNKNOWN` unless a real usage export is supplied.

T0 does not activate convergent behavior. It establishes the comparison point
for shadow, canary, and rollback decisions.
