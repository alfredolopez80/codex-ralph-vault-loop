# PR #74 Review Adjudication — Frozen T14A Finding Set

Status: **ACCEPTED FOR ONE INTEGRATED REPO-LOCAL BATCH**

Adjudicator: **GPT-5.6 SOL Max**

Authority owner: **Codex main**

Adjudicated at: `2026-08-11`

## Frozen identity

```text
task_epoch=pr74-t14a-5b25553
plan_id=ralph-convergent-execution-v4-20260811
plan_version=1
plan_digest=sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1
constitution_digest=sha256:1dfb089692c88308ebc887d8ecedb6dc9bfedb0d602ea43160318cef22196f6d
policy_hash=sha256:aa7847050dad0821c83f456b31a42efa0d6eea8989b22b33ecc6edb2c26adbef
decision_fingerprint=sha256:b623505289618c5371973ac0fa8412ca76cfb37a5cd52691cf40d9a8273f5c72
approval_evidence_digest=sha256:047df9202a71840d144bbad775533ed65465c3ca6002cd6aa2c06548dbab66ad
repository=alfredolopez80/codex-ralph-vault-loop
pull_request=74
base_sha=78a314b47e6a1017b6d369358fda4c6c28450e06
reviewed_head_sha=5b25553e7327c81f6e2ae772837c42cb23fd70ad
historical_thread_count=52
current_thread_count=28
finding_set_digest=sha256:437ffd3ed76f781214855bb0d3ad26eb5e511600fa9e255aedb1abbaf7aad0a6
```

The finding-set digest is computed from the PR, base, reviewed head, historical
count, and the sorted current review-comment IDs below. Review bodies are
deliberately excluded. This artifact stores only bounded metadata and
content-safe obligations.

## SOL Max verdict

All 28 current findings are valid. They expose twelve coupled root causes:
caller-derived provenance, incomplete typed bindings, phase-insensitive
mutation, reason-text lifecycle routing, incomplete hook graph identity,
fail-open authority paths, retry-unsafe prompt initialization, unbounded or
unbound executable/config inputs, incomplete review/amendment authority,
non-repairable terminal transitions, permissive recall eligibility, and
detached-worktree repository ambiguity.

The correct solution is one integrated contract batch. Treating the findings
as isolated patches would leave cross-contract gaps between the reducer,
store, hook adapters, authority resolver, final audit, effective graph, recall,
and SessionStart recovery. The approved batch may change material lifecycle
and authority contracts under AM-001. It must not reset any v1 budget or alter
the immutable plan bytes. Global T15 installation remains excluded.

## Current finding obligations

| Review comment | Priority | Surface                     | Classification           | Content-safe obligation                                                                |
| -------------- | -------- | --------------------------- | ------------------------ | -------------------------------------------------------------------------------------- |
| `3758273663`   | P2       | `final_audit.py`            | `DIRECT_LOCAL_FIX`       | Validate every audit digest with the strict SHA-256 contract.                          |
| `3758273695`   | P1       | `progress_hook.py`          | `MATERIAL_DESIGN_CHANGE` | Bind implicit plan selection to canonical branch, HEAD and repository provenance.      |
| `3758273707`   | P2       | `convergent_store.py`       | `DIRECT_LOCAL_FIX`       | Freeze transition-bound artifacts after their mutation window and at closure.          |
| `3758791222`   | P1       | `final_audit.py`            | `DIRECT_LOCAL_FIX`       | Require a strict evidence digest for every executed passing gate.                      |
| `3758791232`   | P1       | `effective_hook_graph.py`   | `DIRECT_LOCAL_FIX`       | Bind each semantic owner to its required lifecycle event.                              |
| `3759074556`   | P1       | `convergence_authority.py`  | `MATERIAL_DESIGN_CHANGE` | Rotate canonical task state on a classified new-task boundary.                         |
| `3760088546`   | P1       | `session_start_dispatch.py` | `DIRECT_LOCAL_FIX`       | Compare supplied SessionStart identity with canonical active identity before fallback. |
| `3760088555`   | P1       | `convergent_reducer.py`     | `DIRECT_LOCAL_FIX`       | Persist final-audit repair origin structurally, independent of free-form reason text.  |
| `3760088568`   | P1       | `effective_hook_graph.py`   | `DIRECT_LOCAL_FIX`       | Detect duplicate effective registrations instead of collapsing role names.             |
| `3760088575`   | P1       | `convergent_store.py`       | `MATERIAL_DESIGN_CHANGE` | Require a typed approval artifact and Codex-main actor for approval-bound AMEND.       |
| `3760088582`   | P2       | `convergence_authority.py`  | `DIRECT_LOCAL_FIX`       | Keep shadow prompt evaluation off Git subprocesses.                                    |
| `3760088590`   | P1       | `convergent_contracts.py`   | `DIRECT_LOCAL_FIX`       | Validate and journal risk changes in state patches.                                    |
| `3760357242`   | P1       | `user_prompt_dispatch.py`   | `DIRECT_LOCAL_FIX`       | Convert enforce authority/state failures into one supported fail-closed decision.      |
| `3760357248`   | P1       | `convergent_store.py`       | `DIRECT_LOCAL_FIX`       | Restrict amendment append and packet replacement to AMEND-eligible phases.             |
| `3760357255`   | P1       | `convergent_reducer.py`     | `MATERIAL_DESIGN_CHANGE` | Bind Micro/Quick Aristotle transitions to validated typed output evidence.             |
| `3760357260`   | P1       | `effective-hook-graph.py`   | `DIRECT_LOCAL_FIX`       | Hash supported interpreter script operands or reject an unbound bundle.                |
| `3760357262`   | P1       | `convergent_reducer.py`     | `MATERIAL_DESIGN_CHANGE` | Route Stop continuation to the concrete repair phase and invalidate stale audit state. |
| `3760357267`   | P1       | `convergent_store.py`       | `MATERIAL_DESIGN_CHANGE` | Bind final-audit HEAD evidence to independently resolved checkout HEAD.                |
| `3760357272`   | P2       | `convergence_authority.py`  | `MATERIAL_DESIGN_CHANGE` | Make prompt initialization/classification retry-safe as one logical transaction.       |
| `3760357280`   | P2       | `stop_dispatch.py`          | `DIRECT_LOCAL_FIX`       | Normalize Stop recovery store/integrity failures to one supported block.               |
| `3760357287`   | P2       | `convergent_store.py`       | `DIRECT_LOCAL_FIX`       | Preserve immutable review-ledger header metadata during triage.                        |
| `3760357296`   | P2       | `convergent_store.py`       | `DIRECT_LOCAL_FIX`       | Bind Decision Packet version to canonical Aristotle decision version.                  |
| `3760357302`   | P2       | `execution_policy.py`       | `DIRECT_LOCAL_FIX`       | Read the activation descriptor through a bounded no-follow regular-file descriptor.    |
| `3760357307`   | P1       | `convergent_reducer.py`     | `MATERIAL_DESIGN_CHANGE` | Reopen material work from frozen analysis without consuming a second Aristotle run.    |
| `3760357311`   | P1       | `convergent_hooks.py`       | `DIRECT_LOCAL_FIX`       | Reject attached `fd`/`fdfind` exec options from the successful-read fast path.         |
| `3760357317`   | P2       | `decision_packet.py`        | `DIRECT_LOCAL_FIX`       | Reject no-op Decision Amendments.                                                      |
| `3760357327`   | P2       | `recall_delta.py`           | `DIRECT_LOCAL_FIX`       | Select recall only from an explicit eligible-status allowlist.                         |
| `3760357332`   | P2       | `progress_hook.py`          | `MATERIAL_DESIGN_CHANGE` | Bind detached-primary recovery to durable original-repository identity.                |

## Frozen impact matrix

| Surface                   | Expected impact                                                                                              | Required invariant                                                                       |
| ------------------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| Authority and approval    | New task epochs, approval-bound AMEND and retry recovery become explicit typed operations.                   | Only Codex main may authorize material AMEND; caller hints never become authority.       |
| RED and egress            | No body, prompt, review text or credential is persisted or externalized.                                     | Existing RED-local and egress rules remain unchanged.                                    |
| State and persistence     | Adds typed bindings/patch fields and narrows mutation windows; no schema downgrade or budget reset.          | Replay, CAS, idempotency, append-only amendment and immutable closure remain valid.      |
| Hooks and plugins         | Canonical event ownership, duplicate-registration detection and interpreter operand binding become complete. | One effective owner per lifecycle/event/domain; unknown executable content fails closed. |
| Git and worktree          | SessionStart, final audit and detached recovery bind to independently derived repository identity and HEAD.  | Payload branch/SHA/path values cannot authorize a foreign checkout.                      |
| Compatibility             | Existing valid v4 states remain readable; retry and reopen gain explicit legal paths.                        | No hidden legacy fallback in enforce mode.                                               |
| Tests and CI              | Focused unit/integration coverage is required for every obligation, then hook/memory/minimal gates.          | Production contracts drive tests; no test-only weakening.                                |
| Documentation and rollout | AM-001/T14A records the approved generation and exact evidence.                                              | T15 global install remains unexecuted until a separate Codex-main gate.                  |
| Rollback                  | Repo changes are reversible as one batch before publication.                                                 | Plan v1 digest and existing counters remain byte-for-byte unchanged.                     |

## Frozen verification matrix

1. Exact identity: `HEAD`, base, branch, clean-entry proof and plan SHA-256.
2. Contract suites: convergence contracts, reducer, store, final audit, goal and
   amendment tests.
3. Lifecycle adapters: UserPromptSubmit, SessionStart, PostTool and Stop tests,
   including supported single-block output.
4. Effective graph: event ownership, duplicate project/global registration,
   interpreter operands and bundle tamper rejection.
5. Memory/provenance: recall eligible-status allowlist and detached-primary
   repository mismatch rejection.
6. Plan workflow: implementation-notes focused tests and canonical index
   validation.
7. Repository gates: hook smoke, memory-flow validation, minimal gates and
   `git diff --check`.
8. Final identity: actual final `HEAD`/worktree evidence is reported separately;
   no T15 install, commit or push is performed by this batch owner.

## Rejected alternatives

- Per-comment patches: rejected because reducer/store/adapter invariants cross
  file boundaries and would reopen the same review loop.
- Reason-string routing: rejected because lifecycle state must be typed.
- Caller-provided approval, branch, SHA or HEAD booleans: rejected because they
  are not independent authority.
- Legacy fallback in enforce mode: rejected because it bypasses canonical
  convergence state.
- Resetting review, amendment, Aristotle, repair or Stop budgets: rejected by
  plan v1 and AM-001.

## Remaining decision boundary

No further user decision is required for this repo-local batch. A new
`USER_DECISION` is required only if implementation reveals an additional
independent material contract not represented above, or before global T15
installation/activation.
