# Solution Architecture Adjudication — Anti-Loop Amendment

Status: **PROPOSED — non-authoritative until explicit USER_DECISION**

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

## Current PR boundary

This proposal governs the remaining PR review and prevents the observed
eleven-commit patch loop. It describes the direct local hardening already
determined by the v4 contracts (bounded finding iteration, canonical boundary
wire values, fail-closed unknown guarded plugins, bounded plan hashing, and
non-empty Aristotle evidence). It does **not** authorize wiring the full
PostTool material lifecycle, trusted runtime attestation, global installation,
or production rollout. Those are material design changes and remain separate
goals requiring a new approved plan generation or explicit user decision.

The canary remains structural-only. Provider credits, live SOL/model turns,
wall time, escaped defects, full lifecycle equivalence, and global hook writes
remain `UNKNOWN` unless measured in a paired runtime lane. Repo-local shadow is
allowed by the existing T13 user decision; T15 global install remains outside
this PR.

## Done when

- each current review finding has one adjudication classification and evidence;
- direct fixes are delivered in one bounded correction batch;
- no automatic re-review or budget reset occurs;
- architectural boundaries are recorded rather than papered over with
  patches;
- fresh-clone CI and the local gates pass on one published SHA; and
- the final SOL Max validation names any remaining `USER_DECISION` boundary.
