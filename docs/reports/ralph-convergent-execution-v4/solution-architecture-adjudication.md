# Solution Architecture Adjudication — Anti-Loop Amendment

Status: **APPROVED — T14A CLOSED; T15 GLOBAL ENFORCE VALIDATED**

Plan: `ralph-convergent-execution-v4-20260811`

Plan version: `1` (immutable)

Plan digest: `sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1`

## Decision

Every bug, issue, review finding, CI failure, or follow-up comment is evidence,
not patch authorization. Before the first write for one evidence set, the
stable implementation owner must perform one GPT-5.6 SOL Max Solution
Architecture Adjudication bound to the current plan digest, policy hash,
Decision Packet fingerprint, task epoch, worktree, branch, and reviewed HEAD.
Codex main remains the authority for scope, edits, approvals, integration and
closure.

The adjudication must reproduce the symptom (or record why reproduction is
impossible), perform a root-cause autopsy against the plan, constitutional
invariants, architecture, persistence and public contracts, security and
approval boundaries, and current source, then classify the evidence as one of:

`DIRECT_LOCAL_FIX`, `MATERIAL_DESIGN_CHANGE`, `FALSE_POSITIVE`,
`PRE_EXISTING`, `DEFER_FOLLOW_UP`, or `NEEDS_USER_DECISION`.

For `DIRECT_LOCAL_FIX`, SOL Max selects the smallest direct solution that
removes the root cause without a fallback, placeholder, contract weakening, or
test-only production change. It freezes an impact matrix and verification
matrix before edits. Any new state/schema/policy/budget/authority rule, hook
ownership rule, trust boundary, migration, rollout boundary, allowed path,
goal, or user-scope change is a `MATERIAL_DESIGN_CHANGE` and stops in
`USER_DECISION` before mutation. A boolean `approval_required` is not approval:
critical or material amendments require persisted, bounded approval evidence.

## Finite convergence rule

Review identity is task-epoch plus work item, not commit, session, reviewer or
review ID. A newer comment does not reset review, amendment, repair, or Stop
budgets. Follow-up evidence is captured as one bounded set and adjudicated; it
cannot directly authorize a patch, invoke another reviewer, rerun Aristotle, or
reset a counter.

The workflow permits at most one post-mitigation correction batch, only for a
`DIRECT_LOCAL_FIX` that consumes the existing repair budget. A second follow-up
batch, repeated failure fingerprint, independent root cause after correction,
material redesign, missing approval, or exhausted budget becomes
`USER_DECISION`. Automatic re-review after a patch is zero. `CLOSED` is
immutable; new work creates a new task epoch.

## Required evidence before a write

The content-safe adjudication record must bind:

- `task_epoch`, `plan_digest`, `decision_fingerprint`, `policy_hash`, and the
  reviewed HEAD digest;
- a bounded `finding_set_digest`, finding IDs, evidence IDs, violated
  contracts, root cause, classification, selected solution, rejected
  alternatives, and changed/unchanged surfaces;
- an impact matrix covering authority/approval, RED and egress, state and
  persistence, hooks/plugins, Git/worktree scope, compatibility/migration,
  tests/CI, documentation/canary/rollout, and rollback;
- a verification matrix with falsifiable gates; and
- rollback actions plus an approval-evidence digest when approval is required.

The record is append-only, content-safe, immutable per finding-set digest, and
idempotent: the same operation and payload is a no-op; the same operation with
different payload is a conflict.

## Current PR boundary and outcome

The user approved this adjudication and the material control-plane changes
needed to close the current review surface. One content-safe adjudication was
frozen for the 28 current threads at reviewed HEAD
`5b25553e7327c81f6e2ae772837c42cb23fd70ad`, with finding-set digest
`sha256:437ffd3ed76f781214855bb0d3ad26eb5e511600fa9e255aedb1abbaf7aad0a6`.
The implementation then applied one coherent correction batch for the direct
contracts and core guards.

The batch closes the three repo-local control-plane surfaces: authority now
binds enforce decisions to the content-addressed manual activation approval,
the actual full checkout HEAD and the atomic initialization operation; a distinct task epoch
is archived behind an active CAS pointer without resetting budgets; and
PostTool commits only bounded, typed evidence through an evidence-only store
transition. Their local evidence is recorded in
`t14a-implementation-residual.json`. The explicitly authorized T15 global
installation ran from `main` at `b889243ddc001430d7aafe7358eb80e75bb28822`;
backup, hook parity, effective doctor, model-visible skill discovery, smoke
and isolated rollback rehearsal all passed. The manual activation amendment
promotes the global wrapper to enforce; `off` remains the explicit rollback
mode and `shadow` is retired.

The canary remains structural-only. Provider credits, live SOL/model turns,
wall time, escaped defects, full lifecycle equivalence, and global hook writes
remain not measured unless their authoritative evidence sources are present;
no subscription-credit or provider-savings claim is derived from the
structural canary.

## Done when

- each current review finding has one adjudication classification and evidence;
- direct fixes are delivered in one bounded correction batch;
- no automatic re-review or budget reset occurs;
- architectural boundaries are recorded rather than papered over with
  patches;
- focused local gates pass for the published batch and fresh-clone CI remains
  a Codex-main publication gate; and
- the final SOL Max validation separates repo-local closure from the live T15
  rollout evidence rather than reopening the correction batch.
