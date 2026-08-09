# Runtime optimization v2 — Phase 17 adversarial review

Date: 2026-08-09

Baseline: `4784a55dd2b33e874ff8e615c6afe1488a8402dc`

Reviewed candidate before remediation: `7543e206b7cf25d114b2f0743fe40560586f5ffb`

Remediation: the commit containing this report

## Verdict

The first, read-only pass was **NO-GO**: 0 critical, 8 high, 13 medium,
4 low, and 6 false-positive findings. The remediation pass changed only
validated high/medium findings and added focused regression evidence. The
third pass found no open critical, high, or medium finding.

**Recommendation:** GO for a repository-local or otherwise isolated canary.
Machine-wide/global activation remains gated: the currently installed global
checkout is the stable baseline and therefore fails the new dispatcher
doctor/smoke checks. Phase 17 intentionally did not modify the user-level
Codex directory or install global hooks.

This review does not claim exact model units, cached input, billing,
subscription, credit, or account-limit measurements. The context-unit field
remains a documented byte-derived heuristic and subscription measurement is
always reported as false.

## Review method and independence

The baseline SHA was recovered from the Phase 16 report, which records it as
the SHA from `00-baseline.md`; that source file is not present in the current
tree. Before editing, the review inspected the complete baseline range with:

```text
git diff --stat 4784a55dd2b33e874ff8e615c6afe1488a8402dc...7543e206
git diff --name-status 4784a55dd2b33e874ff8e615c6afe1488a8402dc...7543e206
git log --oneline 4784a55dd2b33e874ff8e615c6afe1488a8402dc..7543e206
```

The reviewed range contained 106 tracked files, 10,126 insertions, and 1,136
deletions. One read-only SOL/max reviewer was used, within the explicit limit;
Codex main independently checked every accepted finding against code and tests.
The first-pass inventory below was frozen before the first edit.

## First pass — validated high findings

Each row includes the pre-fix location, evidence, impact/reproduction, the
smallest accepted correction, and its regression proof.

| ID  | Location and evidence                                                                                                                                                                                                                                                             | Impact and reproduction                                                                                                                                                                                                                              | Minimal correction and required test                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Status   |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| H01 | `7543e206:.codex/hooks.json:14-43` configured five `UserPromptSubmit` processes and had no context-fingerprint cache.                                                                                                                                                             | Every submission reparsed state and could repeat recall/context. Inspect handler count or run `repeated_prompt`.                                                                                                                                     | Configure one `.codex/hooks/user_prompt_dispatch.py` (`.codex/hooks.json:16-27`), cache only hashes/IDs in `shared/context_delta.py:191-343`, and cap profile output. `tests/unit/test_user_prompt_dispatch.py:65-137`; `tests/unit/test_context_delta.py:44-108`.                                                                                                                                                                                                                                                         | Resolved |
| H02 | `7543e206:.codex/hooks.json:45-64` configured three independent PreToolUse guards. No process owned the complete `deny > rewrite > allow` order.                                                                                                                                  | Triple parsing and ambiguous cross-handler precedence could weaken a deny or create incompatible output. Reproduce with a destructive spawn payload across the three wrappers.                                                                       | One deny-first `.codex/hooks/pre_tool_dispatch.py:128-160`; aliases, sensitivity, path and routing checks remain internal. `tests/unit/test_pre_tool_dispatch.py:58-132`.                                                                                                                                                                                                                                                                                                                                                  | Resolved |
| H03 | `7543e206:.codex/hooks/global_hook_dispatch.py:123-150` looked for only one workspace-local config and suppressed only an exact role/matcher pair.                                                                                                                                | A nested cwd or legacy/consolidated semantic equivalent could execute both project and global hooks. Reproduce from a nested directory with both configurations.                                                                                     | Resolve the effective project config through bounded ancestors and compare event, semantic role, and matcher in `.codex/hooks/global_hook_dispatch.py:131-193`. `tests/integration/test_effective_hook_chain.py:138-178`.                                                                                                                                                                                                                                                                                                  | Resolved |
| H04 | `7543e206:.codex/hooks/subagent_routing_pretool_guard.py:306-310` and `sol_advisor_pretool_guard.py:40-43` accepted omitted fork metadata for managed SOL/Terra spawns.                                                                                                           | Native omission can inherit full history, defeating packet caps and local-data boundaries. Reproduce a managed spawn without `fork_turns`.                                                                                                           | Require explicit no-history fork and restrict the SOL guard to native spawn tools (`subagent_routing_pretool_guard.py:303-310`; `sol_advisor_pretool_guard.py:19-49`). `tests/unit/test_sol_advisor_hooks.py:706-727,779-820`.                                                                                                                                                                                                                                                                                             | Resolved |
| H05 | `7543e206:.codex/hooks/shared/continuation_budget.py:138-168` returned an exhausted-looking reservation on storage failure.                                                                                                                                                       | A real hard failure could be allowed for the wrong reason and telemetry would falsely say the continuation budget was consumed. Make both runtime roots unsafe.                                                                                      | Separate `storage_error` from `exhausted`, try the approved fallback state root, then allow with an explicit local warning (`continuation_budget.py:192-217`; `stop_dispatch.py:148-167`). `tests/unit/test_stop_dispatch.py:271-306`.                                                                                                                                                                                                                                                                                     | Resolved |
| H06 | `7543e206:.codex/hooks/stop_persist_memory.py:51-65` persisted a verbatim assistant excerpt into handoff/normal learning; `user_prompt_capture.py:32-47` persisted submitted-text terms and a full workspace path; SessionStart output was not delimited as untrusted continuity. | Data fragments or instruction-shaped content could persist and later re-enter model context. Reproduce with sentinel strings and inspect runtime files/startup output.                                                                               | Persist only a submission hash and workspace ID (`user_prompt_capture.py:22-37`), content-free handoff/checkpoint metadata plus human-review-only candidates (`stop_persist_memory.py:23-92`), exclude candidates from recall (`scripts/memory/ralph-recall.py:195-206`), and delimit startup context (`session_start_dispatch.py:36-38,365-390`). `tests/integration/test_worktree_project_isolation.py:305-349`; `tests/unit/test_stop_dispatch.py:319-338`; `tests/integration/test_stop_handoff_checkpoint.py:71-159`. | Resolved |
| H07 | `7543e206:.codex/hooks/shared/stop_scope.py:64-70,76-97,143-168` double-hashed explicit task IDs, included HEAD in the continuation key, and required exact SHA text equality.                                                                                                    | One task could regain continuation budget after a commit; a valid short/full SHA pair could be treated as foreign and bypass a current objective gate. Reproduce with the same task across two HEADs and with 12/40-character forms of the same SHA. | Preserve safe opaque task IDs, exclude HEAD/turn from the task budget key, and accept only prefix-equivalent SHAs (`stop_scope.py:65-103,146-182`). `tests/unit/test_runtime_state_hardening.py:59-91`; Stop budget loop tests remain in `tests/unit/test_stop_dispatch.py:112-132,242-270`.                                                                                                                                                                                                                               | Resolved |
| H08 | `7543e206:scripts/evals/hook_runtime_cost_benchmark.py` and `scripts/gates/runtime_optimization_gate.py` mixed hard-coded handler/scenario assumptions with incomplete scenario evidence.                                                                                         | A report could pass without proving the full profile/scenario matrix, actual configured/matched/executed counts, caps, or child-process observability. Reproduce by deleting a case or changing a configured handler.                                | Derive hooks/matchers from config, execute isolated deterministic scenarios, reject missing samples, and hard-gate the complete matrix (`hook_benchmark_config.py`, `hook_benchmark_scenarios.py`, `hook_benchmark_results.py`; `runtime_optimization_gate.py:232-288`). `tests/unit/test_hook_runtime_cost_benchmark.py:36-184`; `tests/unit/test_runtime_optimization_gate.py:185-225`.                                                                                                                                  | Resolved |

## First pass — validated medium findings

| ID  | Location and evidence                                                                                                                               | Impact and reproduction                                                                                                                                         | Minimal correction and required test                                                                                                                                                                                                                                                                                     | Status   |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- |
| M01 | `7543e206:.codex/hooks/shared/post_tool_state.py:130-248` used one dedupe stage for terminal calls and streaming polls.                             | `exec_command` plus `write_stdin`/poll could suppress a terminal result or persist twice. Replay one originating tool ID through partial and terminal payloads. | Add normalized `result_stage`, original-call ID aliases, and `post-tool-dedupe-v2` (`post_tool_state.py:94-168`); skip persistence for partial events (`post_tool_dispatch.py:194-228`). `tests/unit/test_post_tool_dispatch.py:156-190`.                                                                                | Resolved |
| M02 | `7543e206:.codex/hooks/shared/session_context_cache.py:39-69,118-170` did not reject a symlinked runtime root before directory creation/open.       | A local symlink could redirect state outside the approved runtime.                                                                                              | Harden every parent and fail open; use private permissions and no-follow lock opens. `tests/unit/test_runtime_state_hardening.py:17-33`.                                                                                                                                                                                 | Resolved |
| M03 | `7543e206:.codex/hooks/shared/sol_advisor.py:73-130` followed configured root/session symlinks.                                                     | Advisor budget/route state could escape its approved state root.                                                                                                | Validate root and session components before locked/atomic writes. `tests/unit/test_runtime_state_hardening.py:35-57`.                                                                                                                                                                                                    | Resolved |
| M04 | `7543e206:.codex/hooks/shared/maintenance_queue.py:345-364` debounced on project/workspace/branch/SHA without memory generation.                    | New memory could be silently folded into an older job.                                                                                                          | Include `source_generation` in job identity and debounce (`maintenance_queue.py:270-320,358-370`). `tests/unit/test_maintenance_queue.py:32-60`.                                                                                                                                                                         | Resolved |
| M05 | `7543e206:.codex/hooks/shared/maintenance_queue.py:244-263` reclaimed every expired lease, including the final attempt.                             | A crashing final attempt could loop instead of reaching a bounded terminal state.                                                                               | Dead-letter an expired final lease (`maintenance_queue.py:252-265`). `tests/unit/test_maintenance_queue.py:62-75`.                                                                                                                                                                                                       | Resolved |
| M06 | The pre-fix maintenance runner trusted queued workspace/branch/HEAD descriptors after claim.                                                        | A forged or stale descriptor could run maintenance against another workspace state. Reproduce with a mismatched workspace identity or HEAD.                     | Revalidate project, workspace, branch and prefix-equivalent HEAD immediately before spawning (`maintenance_queue.py:403-430`; runner validation call). `tests/unit/test_maintenance_queue.py:77-87`; `tests/unit/test_maintenance_runner_validation.py:54-89`.                                                           | Resolved |
| M07 | Pre-fix failed native Terra launches did not reliably release their worker reservation because no SubagentStart callback occurs.                    | One failed launch could strand the task budget until lease expiry.                                                                                              | Correlate failed native spawn identity/brief and release only that worker reservation (`shared/sol_advisor.py:1357-1447`). `tests/unit/test_worker_reservation_lifecycle.py:42-78`.                                                                                                                                      | Resolved |
| M08 | `7543e206:.codex/hooks/sol_advisor_pretool_guard.py:20-50` evaluated advisor state for unrelated tools.                                             | Unrelated calls could be blocked or incur needless state reads.                                                                                                 | Early-return unless the canonical tool is native `spawn_agent` (`sol_advisor_pretool_guard.py:19-29`). Covered by advisor/pre-dispatch tests.                                                                                                                                                                            | Resolved |
| M09 | `7543e206:.codex/hooks/post_tool_dispatch.py:84-102` classified by the first shell executable without rejecting control operators.                  | `cat file && mutate` could be treated as read-only and skip write/checkpoint components.                                                                        | Mixed shell operators make the command non-read-only (`post_tool_dispatch.py:67-78`). `tests/unit/test_post_tool_dispatch.py:192-202`.                                                                                                                                                                                   | Resolved |
| M10 | `7543e206:.codex/hooks/shared/runtime_observability.py:104-110,187-220` normalized an already-normalized event a second time and rehashed safe IDs. | Stored identities differed from the reported identity, breaking correlation.                                                                                    | Recognize schema-safe hashed IDs before hashing again and separate normalized storage (`runtime_observability.py:73-91`; `runtime_event_store.py`). `tests/unit/test_runtime_observability.py:86-103`.                                                                                                                   | Resolved |
| M11 | Active dispatchers resolved git through subprocesses while telemetry reported too few children.                                                     | Runtime/process attribution understated scaffold work.                                                                                                          | Reuse payload context with `resolve_git=False` on active hot paths and count only known children (`post_tool_dispatch.py:197`; equivalent prompt/Stop paths). Benchmark schema marks whether child count is measured. Relevant observability and benchmark tests pass.                                                   | Resolved |
| M12 | Pre-fix PostTool metrics/cost JSONL and `directory_bytes` could grow/traverse without the Phase 17 bounds.                                          | Long-running sessions accumulated unbounded I/O and latency.                                                                                                    | Add rotating locked JSONL (`post_tool_ledger.py:19-85`), rotating runtime events (`runtime_event_store.py:21-115`), bounded dedupe entries, and a 512-entry/16 MiB traversal ceiling (`post_tool_state.py:307-327`). `tests/unit/test_post_tool_dispatch.py:204-258`; `tests/unit/test_runtime_observability.py:72-116`. | Resolved |
| M13 | `7543e206:.codex/hooks/user_prompt_capture.py:18,66-84` used a 12 s child timeout inside a 10 s outer handler and limits were duplicated in config. | The fallback could never complete before the outer kill; context caps could drift.                                                                              | Centralize external, child and context budgets (`shared/runtime_budget.py:7-59`), set child to 8 s, and retain positive event-compatible limits in `.codex/hooks.json`. `tests/unit/test_runtime_budget.py`; hook config lockstep tests.                                                                                 | Resolved |

## Low findings accepted for this phase

| ID  | Finding                                                                                                   | Evidence and disposition                                                                                                                                                                                                                |
| --- | --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| L01 | Inactive compatibility wrappers preserve older internal behavior and increase maintenance surface.        | `.codex/hooks/global_hook_dispatch.py` retains explicit legacy role aliases. They are not configured as active handlers; keeping them is an intentional migration contract. Remove only in a separately announced compatibility phase.  |
| L02 | `child_process_count` is attribution of known children, not full process-tree tracing.                    | `hook_benchmark_results.py:48-50` labels measurable known children. No process-inspection dependency was added. Reports must retain this limitation.                                                                                    |
| L03 | PostToolUse still uses the sole broad matcher and may execute one lightweight process for a trivial read. | `.codex/hooks.json:42-50`; internal classification prevents checkpoint/memory writes for trivial reads. This preserves minimal telemetry and matches the accepted Phase 08 policy.                                                      |
| L04 | The referenced `docs/reports/runtime-optimization-v2/00-baseline.md` is absent from the current tree.     | `16-ab-evaluation.md:4-6` preserves the exact SHA and attribution, so review is reproducible, but the original evidence artifact should be restored in a future documentation-only change if available. No baseline value was invented. |

## False positives rejected

| ID   | Claim                                                                                  | Adjudication                                                                                                                                                                                     |
| ---- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| FP01 | `PostToolUse` matcher `.*` is itself a security/performance regression.                | False positive: it is the single explicitly broad handler; internal selection keeps read-only persistence minimal and benchmark counts it honestly.                                              |
| FP02 | `mcp__.*` in the PreTool matcher is over-broad and should be removed.                  | False positive: external MCPs require local classification before dispatch. The matcher is not the only barrier; the dispatcher checks the canonical tool internally.                            |
| FP03 | Presence of `stop_memory_promotion_review.py` means heavy promotion still blocks Stop. | False positive: active Stop config invokes only `stop_dispatch.py`; the compatibility wrapper enqueues and exits.                                                                                |
| FP04 | Presence of dream/vault review scripts means SessionStart still runs maintenance.      | False positive: active SessionStart calls only `session_start_dispatch.py`; benchmark child count is zero even with backlog.                                                                     |
| FP05 | Legacy hook scripts cause project/global duplicate execution.                          | False positive after semantic suppression: active configs contain one role per event, and nested project/global tests prove suppression. Files remain only for direct compatibility diagnostics. |
| FP06 | `estimated_context_units` represents real tokens or subscription cost.                 | False positive: schema/docs call it a byte-derived heuristic and force `subscription_usage_measured=false`.                                                                                      |

## Second pass — correction boundaries

No opportunistic feature or broad refactor was added. Corrections were limited
to consolidation that Phase 16 had proved missing, state/identity hardening,
content-free persistence, deterministic measurement, and the smallest tests
needed to reproduce each validated finding. Production allow/report-only paths
remain stdout-empty; operational persistence failures fail open; objective
security gates and deny precedence remain fail-closed when an action is known.

The final self-review found one incomplete H07 detail: Stop accepted neither a
short nor full textual form of the same SHA unless the strings were identical.
The final patch changed only that comparison and added direct regression
coverage for prefix equivalence, foreign SHA rejection, stable task identity,
and continuation-key stability.

## Validation ledger

| Validation                                         | Result                                                                                                        |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Targeted Stop/state regression                     | `29 passed`                                                                                                   |
| Broad Phase 17 integration subset                  | `159 passed`                                                                                                  |
| Complete pytest suite after final SHA-prefix patch | `992 passed, 5 subtests passed`                                                                               |
| Hook test script                                   | `ALL_HOOK_TESTS_PASS`                                                                                         |
| Repository doctor                                  | `DOCTOR_PASS`                                                                                                 |
| Minimal gates                                      | `1 passed, 2 skipped, 0 failed`                                                                               |
| Mock coding-model eval                             | score `0.9905`; route correctness `1.0`; unsafe-externalization score `0`                                     |
| Ralph memory-flow validation                       | PASS                                                                                                          |
| Structural runtime gate after final patch          | PASS; baseline 25 handlers, candidate 7; candidate errors `[]`                                                |
| `git diff --check` / Python compile                | PASS                                                                                                          |
| Installed global smoke/doctor                      | Expected FAIL: installed stable baseline lacks new dispatcher sources; no install was authorized or attempted |

The complete pytest and other relevant gates are rerun after the final code
patch before commit; the checkpoint records their final counts.

## Final benchmark evidence

Seven measured iterations followed one separate warmup for every scenario and
LUNA/SOL/UNKNOWN profile. Workspaces, Ralph homes, memory, vault, and state were
temporary and isolated.

| Scenario               | LUNA p95 ms | SOL p95 ms | UNKNOWN p95 ms | Structural/result evidence                                                                   |
| ---------------------- | ----------: | ---------: | -------------: | -------------------------------------------------------------------------------------------- |
| small_read_only        |     116.510 |    117.906 |        123.803 | 2 relevant event dispatches total; stdout 0; children 0                                      |
| small_edit             |     127.099 |    119.244 |        124.053 | Pre + Post, one handler each; stdout 0                                                       |
| medium_edit_test       |     262.183 |    252.444 |        246.337 | 4 matched/executed over two tool calls; stdout 0                                             |
| repeated_prompt        |     281.106 |    294.309 |        283.568 | one handler per submission; second call cache hit; output 1110/575/1110 B; first recall only |
| session_start_startup  |      56.618 |     55.400 |         55.854 | child count 0; output 329/328/345 B                                                          |
| session_start_compact  |      54.358 |     54.691 |         54.427 | child count 0; output 268/267/284 B                                                          |
| stop_allow             |      61.190 |     70.377 |         69.095 | stdout 0; continuation 0                                                                     |
| stop_objective_failure |      71.635 |     67.454 |         66.940 | one compact block/continuation; 173 B                                                        |
| subagent_route         |      59.408 |     58.523 |         62.672 | SOL self-supervision blocked by policy; child count 0                                        |
| red_safety             |      58.908 |     63.542 |         60.102 | one local block; child count 0; no external call                                             |

The final benchmark passes `benchmark_hard_errors=[]`. The structural gate
reports one configured handler for every event, 25 baseline handlers versus 7
candidate handlers, all prompt/session hard caps respected, no Stop loop, no
MCP duplicate, `max_threads=2`, `max_depth=1`, and the AGENTS instruction cap.

A comparison between an earlier one-iteration smoke run and this seven-run
sample labelled several p95 rows as greater than 10% (for example Stop allow
SOL +15.1%). That is a visible **soft noise warning**, not an A/B claim: a
single sample is not a p95 distribution and counts/output/persistence were
unchanged. Against the recorded Phase 16 baseline, the absolute interactive
targets remain comfortably satisfied: SessionStart ~54-57 ms versus 802.3 ms,
Stop ~61-72 ms versus 1103.5 ms aggregate, and the previously missing
UserPrompt/PreTool one-handler structural targets are now met.

## Third pass — residual risk and canary decision

- **Open critical/high:** none.
- **Open medium:** none.
- **Accepted low:** L01-L04 above.
- **Security:** deny precedence, local sensitivity policy, path/symlink checks,
  SFW, production integrity, and objective Stop gates have regression coverage.
- **Correctness:** locks, bounded leases, dedupe stages, scope freshness,
  branch/workspace isolation, SHA prefix identity, and corrupt-state recovery
  were inspected and tested.
- **Memory:** normal recall excludes review candidates; handoff/context carries
  IDs and bounded metadata rather than verbatim submission/assistant bodies;
  provenance and human review remain required.
- **Performance:** active interactive events use one dispatcher each; no hidden
  maintenance is in Stop/SessionStart; JSONL/cache/state are bounded.
- **Compatibility:** wrappers remain available but inactive. The installer,
  generated config, and temporary-HOME global tests are lockstep. Existing
  machine-global state is intentionally not activated in this phase.

Therefore the code is **GO for isolated canary** and **NO-GO for machine-wide
canary until an explicitly authorized global installation is followed by green
global smoke and doctor checks**. No Phase 18 work was started.
