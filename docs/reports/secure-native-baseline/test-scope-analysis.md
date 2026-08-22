# Secure-native baseline: test-scope analysis

**Scope.** Audit and classification of Convergent, lifecycle, activation,
lease, `Stop`, `PostToolUse`, `UserPromptSubmit`, and `SessionStart` tests.
This report does not authorize removal of any test.

## Evidence and counting boundary

The current full-gate result is **1,338 passed, 27 skipped, and 5 subtests**.
The prior approximate keyword inventory found **169 test files**, **1,265 test
functions**, and **556 lifecycle-related functions**, including **149 that
overlap security**. Those are the planning baseline for this analysis.

The keyword figures are an **inventory**, not a deletion list: a match may be a
fixture, a negative security case, an inactive compatibility assertion, or an
active security dependency. Each proposed retirement therefore needs its own
issue-scoped acceptance criteria, active-hook-graph check, and focused test
run before deletion.

For a reproducible, narrower current working-tree snapshot, this audit used
textual discovery only: `rg --files tests -g '*.py'` reported 145 Python test
files; `rg '^def test_' tests` reported 1,205 textual test functions; and an
event/convergence keyword line scan reported 1,093 matching lines. These
figures use a different method and current dirty working tree, so they must not
replace the recorded full-gate or approximate-inventory figures above.

## Active baseline boundary

The effective profile is `security-only`: only `PreToolUse` is registered.
`SessionStart`, `UserPromptSubmit`, `PostToolUse`, `SubagentStart`,
`SubagentStop`, and `Stop` legacy handlers are disabled. Consequently,
Convergent/lifecycle/activation/lease tests are valuable migration evidence but
are not proof that a currently registered security control works.

`scripts/gates/run-gates.py --minimal` deliberately selects four security
signals: the synthetic security baseline, effective-hook-graph doctor,
project/global hook-config lockstep, and secure-native-baseline evaluator.
The lifecycle suite must remain outside that lane. The current run passed all
four checks in about two seconds.

The 18 synthetic fixtures are the versioned representative minimum from
`SECURITY_BASELINE` v3: eight hard blocks, one exact approval case, and nine
allowed cases. They are not a claim that every branch of the active guard is
covered. Standard/full/critical lanes retain the broader security tests,
including local-Minikube, cloud-operation, RED-egress, and malformed-payload
cases. Any new guard branch needs focused coverage there before it can be
considered protected.

## Classification matrix

| Classification                                              | Test scope / representative files                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Basis and required treatment                                                                                                                                                                                                                                                        |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Protects current security**                               | `tests/integration/test_security_baseline.py`; `tests/evals/test_secure_native_baseline.py`; `tests/integration/test_effective_hook_graph_integration.py`; `tests/unit/test_effective_hook_graph.py`; `tests/integration/test_hook_config_lockstep.py::test_local_and_global_hook_configs_stay_in_lockstep`; the active `PreToolUse` security cases in `tests/integration/test_hooks_basic.py`                                                                                                                                                                                                                                                                                                                                                                       | These establish the active `PreToolUse` dispatcher, security-only registration, and the synthetic destructive/egress/workspace/package/cloud boundary. Keep them or replace them with equivalent active-security coverage before any removal.                                       |
| **Migration evidence; must not enter `--minimal`**          | `tests/unit/test_convergent_*.py`; `tests/integration/test_convergent_review_mitigation.py`; `tests/integration/test_hook_lifecycle_e2e.py`; `tests/integration/test_prompt_sol_subagent_lifecycle_e2e.py`; `tests/unit/test_{session_start,user_prompt,post_tool,stop}_dispatch.py`; `tests/integration/test_{post_tool_checkpoint,post_tool_cost_ledger,session_start_sources_integration,progress_session_start_subprocess,stop_handoff_checkpoint}.py`                                                                                                                                                                                                                                                                                                           | They exercise disabled lifecycle/convergence behavior or historical dispatchers. Preserve in standard/full while migration decisions remain open; do not add them to the fast security-only signal. The lifecycle E2E module is explicitly skipped under the security-only profile. |
| **Candidate retirement in #85**                             | The Convergent v4 state-machine and advisor lifecycle set: `test_convergent_reducer_v4.py`, `test_convergent_store_v4.py`, `test_convergent_close_v4.py`, `test_convergent_stop_adapter.py`, `test_convergence_contract.py`, `test_convergence_authority.py`, `test_convergent_canary.py`, `test_convergent_hook_hotpaths.py`, `test_convergent_review_mitigation.py`, and `test_prompt_sol_subagent_lifecycle_e2e.py`                                                                                                                                                                                                                                                                                                                                               | Candidate only if #85 permanently removes the disabled Convergent/advisor architecture. First prove no registration, import, gate, or supported migration path depends on each file; retain any assertion that also covers the active security dispatcher.                          |
| **Candidate retirement in #75**                             | Legacy event-handler suites after their specific replacement/removal decision: `test_session_start_dispatch.py`, `test_user_prompt_dispatch.py`, `test_post_tool_dispatch.py`, `test_stop_dispatch.py`, `test_hook_lifecycle_e2e.py`, `test_post_tool_checkpoint.py`, `test_post_tool_cost_ledger.py`, `test_stop_handoff_checkpoint.py`, and legacy event portions of `test_hooks_basic.py`                                                                                                                                                                                                                                                                                                                                                                         | Candidate only if #75 owns removal of these inactive handler implementations. Split mixed files first: active `PreToolUse` tests are not #75 retirement candidates.                                                                                                                 |
| **Belongs to #76 / #77 / #80 (retain pending issue scope)** | **#76:** `SessionStart`/`UserPromptSubmit` continuity and recovery (`test_session_start_dispatch.py`, `test_session_start_sources_integration.py`, `test_progress_session_start_subprocess.py`, `test_user_prompt_dispatch.py`, `test_effective_hook_chain.py` prompt-context case). **#77:** `PostToolUse`/`Stop` persistence and completion (`test_post_tool_dispatch.py`, `test_post_tool_checkpoint.py`, `test_post_tool_cost_ledger.py`, `test_stop_dispatch.py`, `test_stop_handoff_checkpoint.py`). **#80:** activation, reservations, leases, and advisor routing (`test_manual_activation.py`, `test_sol_advisor_hooks.py`, `test_worker_reservation_lifecycle.py`, relevant `test_maintenance_queue.py`, and `test_prompt_sol_subagent_lifecycle_e2e.py`). | Assignment is by behavior, not filename. These suites should stay available as issue-specific migration evidence until each issue states its final runtime contract and records focused evidence.                                                                                   |

## Overlap rules and safeguards

1. A test may appear in more than one inventory bucket. The 149
   security-overlapping lifecycle matches require manual classification; they
   are not safe to bulk-delete.
2. Mixed suites, especially `tests/integration/test_hooks_basic.py` and
   `tests/integration/test_hook_config_lockstep.py`, must be split by assertion
   behavior before any retirement PR. Their active-profile assertions protect
   the current baseline even where neighboring tests target disabled hooks.
3. Before a #75 or #85 deletion, verify the effective graph stays
   `security-only`, run the four minimal targets, run the affected focused
   tests, and show that the removed test has no active security purpose.
4. A future reactivation of any lifecycle event reverses the presumption here:
   its corresponding tests become candidate active coverage and must be
   reviewed before changing `--minimal`.

## Audit conclusion

The minimal gate is correctly security-only today. The large Convergent and
lifecycle body is historical/migration coverage rather than minimal-gate
coverage. Retire it only in the issue that removes its implementation and
only after preserving the active `PreToolUse` boundary tests; keyword counts
alone never justify deletion.
