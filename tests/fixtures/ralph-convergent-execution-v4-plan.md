# Ralph Convergent Execution v4 — Implementation Plan

Plan ID: `ralph-convergent-execution-v4-20260811`
Plan version: `1`
Plan approval status: approved
Implementation notes: /Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop/.ralph/plans/2026-08-11-ralph-convergent-execution-v4-implementation-notes.html
Implementation notes required: yes
Implementation notes status: active
Starting ref: `origin/main` at `78a314b47e6a1017b6d369358fda4c6c28450e06`
Implementation branch: `codex/ralph-convergent-execution-v4`
Authority owner: `codex-main`
Writable implementation owner: `gpt-5.6-sol`, reasoning `max`
Automatic model fallback: forbidden

## 1. Authority and scope

The normative sources are, in order: the supplied v4 master specification,
the supplied v4 `execution-policy.toml`, the ZIP `DESIGN.md`,
`ADVERSARIAL-ANALYSIS.md`, and `IMPLEMENTATION-PLAN.md`, followed by the v4
section of `README-integration.md`. `index.html` is presentation-only and is
not copied into runtime or used as a policy source. Historical v3 sections are
superseded. The canonical lifecycle diagram is `convergent-execution`; the
duplicate `adaptive-linear-execution` lifecycle is not imported.

The implementation includes runtime code, hooks, tests, policy, repository
documentation, and editable JSON/SVG/PNG diagrams. It excludes the supplied
microsite. Existing Repo Boundary, Git Safety, RED/egress, worktree, Recall,
Stop, and implementation-store invariants must remain active.

## 2. Canonical persistence and goal execution

After approval, this plan is immutable. Its SHA-256 byte digest is computed
before the first goal is created. The canonical progress surface is
`scripts/plans/progress.py`; notes and indexes are derived metadata views.

Required sequence:

1. Verify a clean checkout and `HEAD == origin/main`.
2. Use branch `codex/ralph-convergent-execution-v4`.
3. Start the plan with `progress.py start`.
4. Create the canonical implementation-notes HTML and register the plan in
   `implementation-index.json` and `.md`.
5. Compute and persist `plan_digest`.
6. Compile and activate goals in order.

Every goal record contains `goal_id`, `plan_id`, `plan_version`,
`plan_digest`, `phase_id`, `state_generation`, `objective`, `allowed_paths`,
`forbidden_paths`, `prerequisites`, `done_when`, `required_evidence`, `risk`,
the Codex/SOL owner record, and one of `pending`, `ready`, `active`,
`verifying`, `complete`, `blocked`, or `user-decision`.

Goals are deterministic and serial: `G-BASELINE` (T0-T1), `G-BOUNDARY`
(T2), `G-DECISION` (T3-T4), `G-LEASE` (T5), `G-RECALL-HOTPATH` (T6-T7),
`G-EVIDENCE-CLOSE` (T8-T11), `G-DOCUMENTATION` (T10), `G-SHADOW-CANARY`
(T12-T13), and `G-ROLLOUT` (T14-T15). No goal may invent a miscellaneous
scope, omit `done_when`, operate outside `allowed_paths`, or recompile during
a continuation. A material amendment appends a new generation; it does not
rewrite a completed goal or the plan.

## 3. Runtime contracts

Add a strict v4 policy at `config/execution-policy.toml` and a parser at
`.codex/hooks/shared/execution_policy.py`. It accepts only version 4, rejects
unknown keys/types/enums, records a policy hash, and blocks policy drift in an
active epoch. The exact supplied values are retained, including monotonic
convergence, no automatic model escalation, one Full Aristotle, one material
amendment, zero automatic subagents, one active child maximum, zero/one review
budgets, one ordinary and one distinct-critical Stop continuation, delta-only
Recall, physical read no-ops, deterministic final audit, and canary required.

Add pure contracts/reducer/store modules under
`.codex/hooks/shared/` and reuse the existing implementation-store IO,
locking, atomic publication, bounds, and hash-chain behavior. Do not create a
second human-facing progress store. Convergent control state may live in the
existing plan store's bounded `execution/` namespace.

Task identity is content-safe and includes hashes for session, project,
worktree, objective, task epoch, sensitivity, plan, version, and digest. The
Prompt Boundary returns `boundary_kind`, `risk`, `complexity`, `scope_delta`,
`obligation_delta`, and `approval_delta`. The seven boundary classes are
status, continuation, clarification, new-task, scope-extension,
material-change, and user-override. Prompt length alone cannot create a task.

The tiered Aristotle contract is Micro (complexity 1-2), Quick (3), Full
(4-8/material), and Critical (authorization, security, persistence,
migration, concurrency, public contracts, or production). Full and Critical
produce a versioned Decision Packet with objective, source-of-truth,
assumptions, truths, root cause, invariants, selected solution, rejected
alternatives, affected components, implementation sequence, verification
matrix, review requirement, security/rollout, rollback, done-when,
material-change triggers, and analysis fingerprint.

Material amendment is append-only and includes amendment ID, prior packet
fingerprint, new evidence, invalidated assumption, affected invariants,
design impact, changed/unchanged steps, verification changes, approval state,
and new fingerprint. Automatic amendment budget is one; further redesign is a
user decision.

The persisted state includes schema/policy version and hash, plan/digest,
task/goal/epoch, activation mode, phase/status, execution lease, previous
state hash, Aristotle counters, recall generations and selection digest,
evidence manifest digest, reopen/amendment/repair/review counters,
invalidation/terminal reasons, final-audit digest, open obligations, and
handoff state. Events include operation ID, generation, transition,
precondition digest, evidence IDs, policy hash, previous/new state hashes,
actor role, and terminal/invalidation reason. Raw prompts, RED bodies,
secrets, unsanitized logs, and reviewer output are forbidden.

Identical operation retries are no-ops; conflicting retries, stale
generations, out-of-order events, incomplete JSONL tails, future schemas, and
hash tampering block mutation. Security, Repo/Git, and Stop decisions block on
state-persistence failure; report-only paths remain silent and report
`UNKNOWN`, never fabricated success.

## 4. State machine and budgets

The only normal lifecycle is:

`NEW_TASK -> PROMPT_GATE -> ARISTOTLE -> DESIGN_READY -> IMPLEMENTATION ->`
`FOCUSED_VERIFY -> REVIEW (material/critical only) -> FINDING_TRIAGE ->`
`MITIGATION (accepted findings only) -> FINAL_AUDIT ->`
`ANTI_RATIONALIZATION -> STOP -> CLOSED`.

Permitted backward edges are one material amendment from design/evidence and
bounded repair from focused verification/final-audit regression. Each
transition must advance the phase, reduce obligations, close accepted
findings, consume a non-resettable budget, or reach `CLOSED`, `BLOCKED`, or
`USER_DECISION`. Invalid transitions block. `CLOSED` cannot become active;
new work creates a new task/epoch. `BLOCKED`/`USER_DECISION` require explicit
reopen and never reset counters.

The hard budgets are: Full Aristotle 1, amendment 1, automatic children 0,
active child max 1, nested delegation 0, low-risk review 0, material/critical
review max 1, automatic second review 0, transient rerun 1, one repair per
failure fingerprint, total repairs 3, generative final audit 0 by default,
ordinary Stop continuation 1, distinct critical continuation 1, duplicate
terminal attempt physical no-op. Exhaustion is `USER_DECISION`.

The lease must prove real `gpt-5.6-sol` with `max` reasoning, stable toolset,
CWD, branch, and task epoch. Codex main remains authority. Luna/Terra or a
read-only advisor cannot silently replace the SOL implementation owner.

## 5. Hooks, Recall, review, and close

SessionStart and UserPromptSubmit are metadata/cache-first and emit only
changed deltas. PreTool always evaluates RED/egress, Repo Boundary, Git
Safety, worktree, approval, and delegation. PostTool scans for materiality
before taking a fast path; successful read-only calls with no material signal
perform zero checkpoints, memory extraction, advisor observations, durable
writes, fsync, context injection, or user output. Stop remains authoritative,
performs one aggregate observability write and one sanitized handoff, and
never launches Aristotle, an advisor, a reviewer, or a restart.

Recall's hot key is project/worktree/branch/task/generations/selection/context
epoch; HEAD is provenance only. Same selection and epoch yields zero body
reads and zero context. Context-epoch changes rehydrate once; selection changes
emit a bounded delta. RED, stale, deprecated, conflicting, and wrong-scope
material remain excluded.

The effective-hook doctor inspects global, project, plugin, and legacy sources
and enforces one blocking semantic owner for Prompt Boundary, PreTool safety,
PostTool persistence, and Stop completion. Duplicate blocking owners fail;
duplicate report-only owners warn. The legacy anti-rationalization wrapper
remains unregistered.

Low-risk work has zero generative review. Material/critical work has one
independent read-only review. Findings use a bounded ledger with severity,
location, root cause, impact, evidence, recommendation, and triage status.
Accepted findings are grouped by root cause and repaired in one batch; no
finding-by-finding review loop is allowed. Final audit is deterministic and
checks packet, findings, gates, scope, security, branch/HEAD, blockers,
approvals, notes, and P0/P1 absence. A critical generative final audit is
possible only with explicit approval and is terminal.

## 6. Implementation phases

T0 reconciles source artifacts, verifies the starting SHA, inventories hooks
and the existing store, and records a 24-scenario baseline. T1 adds the
effective-hook graph doctor. T2 adds strict policy parsing and Prompt Boundary
shadow classification. T3 adds tiered Aristotle, goal compiler, and Decision
Packet. T4 adds amendment, reducer, replay, CAS, and crash/concurrency
tests. T5 adds the stable SOL lease and finite delegation. T6 adds Recall
metadata-first/delta behavior. T7 integrates hot paths without bypassing
PreTool safety. T8 consolidates evidence-authoritative
Anti-Rationalization. T9 unifies Stop budgets and terminal no-ops. T10 adds
review/triage/batch mitigation and updates README, architecture, routing,
hooks, progress-store documentation, and seven editable diagrams. T11 adds
deterministic final audit. T12 compares current and candidate behavior in
shadow. T13 runs the same 24 paired scenarios in canary. T14 enables the repo
feature flag only after structural improvement and no quality regression. T15
performs an independently approved global backup/parity/doctor/smoke/rollback
rollout.

Each phase records entry SHA, owned paths, goal state, required evidence,
validation results, implementation notes, and rollback status. A phase cannot
advance with open P0/P1, invalid state, wrong owner, wrong worktree, policy
drift, exhausted budget, missing evidence, or unapproved scope.

## 7. Validation and acceptance

Run the existing focused unit/integration suites, hook tests, memory-flow
validation, minimal gates, and `git diff --check`, plus new tests for every
valid and invalid transition, goal/packet determinism, policy/hash mismatch,
duplicate/out-of-order events, stale generations, crash replay, RED/egress,
Repo/Git/worktree guards, silent hook output, recall no-op/delta behavior,
lease/fallback rejection, review 0/1, batch mitigation, final audit, Stop
budgets, and rollback.

The canary uses the same 24 scenarios in baseline and candidate. Correctness
uses one paired execution; local hook metrics use three repetitions. Credits
are `UNKNOWN` without a real usage export. Canary hard gates require 24/24
scenarios, zero P0/P1, false closes, RED leaks, wrong-worktree operations,
guardrail bypasses, automatic children, second reviews, unchanged recall
injections, successful-read writes, and budget violations. Structural canary
pass additionally requires no regression over 10% in measured wall/context/
hook-write metrics and at least one predeclared structural improvement of 20%.

Rollback is a versioned feature-flag disable plus backup restore, preserving
v4 journals and evidence, without schema downgrade. Global installation,
push, PR, merge, publication, production changes, external writes, and
second generative audits require separate approval.

Done requires the v4 boundary/Aristotle/packet/amendment contracts, stable
SOL lease, preserved safety guardrails, zero automatic subagents, review 0-1,
batch mitigation, deterministic close, effective-hook ownership, read no-op,
Recall delta, complete documentation/diagrams, canary evidence, tested
rollback, canonical implementation notes, and a valid terminal audit digest.
