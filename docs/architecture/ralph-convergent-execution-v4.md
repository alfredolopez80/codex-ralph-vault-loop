# Ralph Convergent Execution v4

Ralph Convergent Execution v4 is a bounded lifecycle for Codex work. Its
constitutional invariant is:

> Every new piece of evidence must move the task monotonically toward `CLOSED`
> or an explicit `USER_DECISION`. No phase may restart an earlier phase
> indefinitely.

## Authority model

Codex main owns scope, decisions, edits, integration, safety, verification,
and final communication. A task-local writable `gpt-5.6-sol` worker with
`max` reasoning may own implementation when its runtime lease proves the model,
effort, toolset, CWD, branch, and task epoch. The lease is stable for the
epoch. A read-only Sol advisor is not an implementation owner and is never
started automatically.

The v4 policy is the exact repository file
[`config/execution-policy.toml`](../../config/execution-policy.toml). It is
separate from `.codex/config.toml`, which remains the Codex runtime
configuration. Policy version or hash drift during an active epoch blocks the
epoch rather than silently changing its rules.

## Finite lifecycle

```text
NEW_TASK → PROMPT_GATE → ARISTOTLE → DESIGN_READY → IMPLEMENTATION
  → FOCUSED_VERIFY → REVIEW (0 or 1) → FINDING_TRIAGE
  → MITIGATION (one batch) → FINAL_AUDIT → ANTI_RATIONALIZATION
  → STOP → CLOSED
```

The only backward edges are one material decision amendment and bounded repair
for a deterministic failure fingerprint. A terminal state never becomes
active through an ordinary continuation; a new task creates a new identity and
epoch. An explicit reopen preserves prior evidence and budgets.

## Prompt Boundary and goals

Every prompt is classified as `status`, `continuation`, `clarification`,
`new-task`, `scope-extension`, `material-change`, or `user-override`. Prompt
length alone never creates a task. A continuation reuses the current Decision
Packet and emits only changed obligations/evidence. A new task creates a new
epoch and a deterministic goal set. A material change uses the single
amendment budget. A status request does not read memory bodies or rewrite a
plan.

Each goal references the immutable plan ID, version, byte digest, phase, state
generation, allowed paths, prerequisites, `done_when`, and required evidence.
Goals are persisted through `scripts/plans/progress.py`; implementation notes
and the implementation index remain canonical local continuity artifacts.

## Aristotle and Decision Packet

Aristotle is tiered by complexity and risk:

- Micro (1–2): objective, assumption, risk, `done_when`.
- Quick (3): assumptions, constraints, proposed move, falsification test.
- Full (4–8/material): assumption autopsy, truths, reconstruction, map, move,
  and a versioned Decision Packet.
- Critical: Full plus threat boundaries, failure modes, migration
  compatibility, rollout, rollback, observability, and abort conditions.

The packet freezes the selected design, invariants, implementation sequence,
verification matrix, review requirement, security/rollout contract, rollback,
and material-change triggers. New evidence may create one append-only
amendment; it never rewrites the original packet. Further redesign is a user
decision.

## Preserved guardrails

| Guardrail            | Convergent behavior                                                |
| -------------------- | ------------------------------------------------------------------ |
| Repo Boundary        | Always evaluated for relevant tools                                |
| Git Safety           | Always evaluated; destructive/remote changes require approval      |
| RED / Egress         | Evaluated before recall, MCP, subagent, vault, handoff, or report  |
| Worktree integrity   | Branch, CWD, and canonical root remain part of evidence            |
| Ralph Recall         | Metadata-first, generation-aware, delta-only                       |
| Anti-Rationalization | Evidence gate at material phase exit and Stop; no new model loop   |
| Stop                 | Final authority; hard gates and terminal budgets are deterministic |

## Efficient hook paths

`SessionStart` and `UserPromptSubmit` use generation and selection metadata
before reading bodies. A cache hit at the same context epoch emits no context
and performs no durable write. A context epoch change performs one bounded
rehydration. A selection change emits only a bounded delta.

`PreToolUse` never bypasses safety for performance. `PostToolUse` first scans
for security, failure, progress, evidence, or memory signals. A successful
read with no material signal is a physical no-op: no checkpoint, memory
extraction, advisor observation, durable ledger row, fsync, context, or user
output. If production cannot measure a fast-path metric, it records `UNKNOWN`
rather than inventing zero.

## Review and deterministic close

Low-risk changes receive zero generative review. Material and critical changes
receive at most one independent read-only review. Findings are fully triaged,
grouped by root cause, and repaired in one batch. The final audit is
deterministic by default and checks the packet/amendment, finding ledger,
focused/full gates, scope, security, branch/HEAD, worktree, blockers,
approvals, notes, and P0/P1 absence. A critical generative final audit is
optional, explicitly approved, and terminal.

## Budgets

The convergence budget is finite: Full Aristotle 1, material amendment 1,
automatic subagents 0, active child at most 1, low-risk review 0,
material/critical review at most 1, automatic second review 0, one repair per
failure fingerprint, three repairs total, ordinary Stop continuation 1, and a
distinct critical continuation 1. Duplicate terminal attempts are physical
no-ops. Exhaustion becomes `USER_DECISION`; it never resets a counter.

## Rollout

The implementation is introduced as off, then shadow, then a same-corpus
canary, then repo-local default, and finally an independently approved global
installation. The current repo-local T14 activation is recorded in
[`config/convergent-execution-mode.toml`](../../config/convergent-execution-mode.toml)
and is bound to the plan and policy hashes. A missing flag resolves to `off`
for unrelated repositories; an explicit `RALPH_CONVERGENT_EXECUTION_MODE=off`
is the rollback path. The canary uses 24 paired scenarios and cannot claim
credit savings without a real usage export. Any false close, RED leak,
wrong-worktree operation, P0/P1, guardrail bypass, or budget violation rejects
the candidate and triggers the versioned rollback flag.
