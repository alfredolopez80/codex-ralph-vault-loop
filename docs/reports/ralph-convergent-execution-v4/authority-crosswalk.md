# Ralph Convergent Execution v4 — Authority Crosswalk

This file is a repository-local, sanitized crosswalk for the immutable
implementation plan. It is not a second plan and does not change the active
`plan_digest`. The detailed constitutional source is preserved beside the
plan at:

`../../../.ralph/plans/2026-08-11-ralph-convergent-execution-v4-constitution.md`

## Authoritative inputs

| Priority | Input                                                 | Digest / repository mapping                                                                                                |
| -------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| 1        | Supplied v4 constitution                              | `1dfb089692c88308ebc887d8ecedb6dc9bfedb0d602ea43160318cef22196f6d`; preserved as the constitution companion                |
| 1        | Supplied execution policy                             | `aa7847050dad0821c83f456b31a42efa0d6eea8989b22b33ecc6edb2c26adbef`; copied byte-for-byte to `config/execution-policy.toml` |
| 2        | ZIP design, adversarial analysis, implementation plan | Reconciled in `docs/architecture/ralph-convergent-execution-v4.md`, runtime contracts, tests and phase evidence            |
| 3        | README integration                                    | Reconciled in `README.md`, `docs/architecture/hooks.md`, `docs/model-level-routing.md` and the diagram README              |
| 4        | `index.html`                                          | Presentation-only; deliberately not copied or used for runtime decisions                                                   |

## Contract-to-evidence map

| Contract                                                                | Implementation                                                                             | Evidence                                                                                                           |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| Closed-world TOML v4, exact hash and epoch drift                        | `.codex/hooks/shared/execution_policy.py`                                                  | `tests/unit/test_execution_policy_v4.py`                                                                           |
| Seven-class Prompt Boundary and enforce/off output contract             | `.codex/hooks/shared/prompt_boundary.py`, `.codex/hooks/user_prompt_dispatch.py`           | `tests/unit/test_prompt_boundary.py`, `tests/unit/test_user_prompt_dispatch.py`                                    |
| Task identity, schema-v3 state/event and immutable aliases              | `.codex/hooks/shared/convergent_contracts.py`                                              | `tests/unit/test_convergence_contract.py`                                                                          |
| Tiered Aristotle, deterministic goals and Decision Packet               | `.codex/hooks/shared/convergent_aristotle.py`, `goal_compiler.py`, `decision_packet.py`    | `tests/unit/test_goal_decision_v4.py`                                                                              |
| Monotonic reducer, CAS, replay, amendment and idempotency               | `.codex/hooks/shared/convergent_reducer.py`, `convergent_store.py`                         | `tests/unit/test_convergent_reducer_v4.py`, `tests/unit/test_convergent_store_v4.py`                               |
| Stable SOL/max lease and bounded delegation                             | `.codex/hooks/shared/execution_lease.py`                                                   | `tests/unit/test_goal_decision_v4.py`, `tests/unit/test_convergent_store_v4.py`                                    |
| Metadata-first Recall Delta                                             | `.codex/hooks/shared/recall_delta.py`                                                      | `tests/unit/test_recall_delta_convergence.py`                                                                      |
| Successful-read physical no-op with always-on PreTool safety            | `.codex/hooks/shared/convergent_hooks.py`, `post_tool_dispatch.py`                         | `tests/unit/test_convergent_hook_hotpaths.py`, `tests/unit/test_post_tool_dispatch.py`                             |
| Evidence-authoritative Stop and finite budgets                          | `.codex/hooks/shared/convergent_stop.py`, `convergent_stop_adapter.py`, `stop_dispatch.py` | `tests/unit/test_convergent_close_v4.py`, `tests/unit/test_convergent_stop_adapter.py`, stop dispatch suites       |
| Review ledger, one mitigation batch and deterministic final audit       | `.codex/hooks/shared/convergent_review.py`, `final_audit.py`                               | `tests/integration/test_convergent_review_mitigation.py`, `tests/unit/test_convergent_final_audit.py`              |
| Effective hook ownership                                                | `scripts/gates/effective-hook-graph.py`                                                    | unit/integration doctor tests and JSON doctor report                                                               |
| Structural canary contract and unmeasured cost handling                 | `scripts/evals/convergent_execution_canary.py`                                             | `canary-structural-report.json`, 24/24 structural scenarios                                                        |
| Rollback and rollout boundary                                           | phase evidence plus feature mode `off` or `enforce`                                        | `docs/reports/ralph-convergent-execution-v4/phase-evidence.md`                                                     |
| SOL Max solution architecture adjudication and finite correction budget | governance amendment, content-safe finding-set evidence, and Codex authority               | `docs/reports/ralph-convergent-execution-v4/solution-architecture-adjudication.md` plus local append-only `AM-001` |
| Test-suite lifecycle and deprecation boundary                           | SOL Max inventory of active, global-lane and retired tests                                 | `docs/reports/ralph-convergent-execution-v4/test-suite-lifecycle-audit.md`                                         |

The repo-local activation contract is versioned at
`config/convergent-execution-mode.toml`. It is bound to the active plan and
policy hashes. A missing activation file resolves to `off` for unrelated
repositories; an explicit `RALPH_CONVERGENT_EXECUTION_MODE=off` remains the
operator rollback path.

Unknown guarded plugin hooks are fail-closed. The only report-only exception is
an exact declaration digest in `config/effective-hook-trust.json`; a matcher
being narrow is not evidence of non-blocking behavior.

## Immutable execution identity

The active plan remains:

```text
plan_id=ralph-convergent-execution-v4-20260811
plan_version=1
plan_digest=sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1
branch=main
entry_sha=a81541c920f5da64c557ff1005febf542b58cb83
```

The canonical progress store is at
`.local-notes/ralph/implementation/plans/ralph-convergent-execution-v4-20260811/`.
Its execution boundary is T14 with an explicit user override recorded in
the append-only journal (`question_opened` seq 21, `question_resolved` seq 23,
validation seq 24) and implementation-notes operation
`ralph-v4-t13-user-override-shadow-activation`; that historical override is
superseded by the manual enforce activation amendment and no longer permits a
shadow execution. Enforce mode and global rollout are established only by the
final-HEAD manual approval and the separate global installer evidence.

The plan, notes and canonical progress state are ignored local artifacts. A
clean clone of this branch therefore contains the runtime
contracts and the immutable plan digest references, but not the active local
ledger; deployment or continuation tooling must provision that ledger and
verify its hashes before treating it as authoritative. The global hook wrapper
is likewise outside this repo-local T14 proof and is not changed by this PR.
