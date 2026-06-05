---
name: goal-refiner
description: Refine rough Codex /goal prompts into concise, verifiable execution contracts. Use for $goal-refiner, goal prompt improvement, or long-running work shaping. Enforce direct /goal payloads under 4000 chars; use GOAL.md/INPUT.md/STATE.md for larger work. Do not execute without separate approval.
argument-hint: "<rough goal, /goal draft, existing GOAL.md path, or long-running task>"
---

# Goal Refiner

Turn rough intent into a goal contract that a coding agent can execute and judge honestly.

The goal text is the exit criteria. It must say what should be true, where to start, what is allowed, what is forbidden, how progress is measured, and what evidence proves completion.

This skill refines the goal. It does not execute the generated implementation task unless the user separately approves execution.

## When To Use

Use this skill when the user explicitly invokes `$goal-refiner`, asks to improve a `/goal`, provides a fuzzy long-running task, wants an existing `GOAL.md` audited, or needs a reviewable handoff for a feature, migration, audit, optimization, deployment, refactor, or test-fix.

Do not use it for tiny direct tasks, general explanations of goal mode, or normal implementation work where the user clearly wants execution now.

## Core Contract

Every refined goal needs four parts:

- `Goal`: the concrete outcome.
- `Context`: files, docs, URLs, errors, plans, tests, repos, or systems to inspect first.
- `Constraints`: scope, safety rules, allowed tools, approval gates, cost limits, and prohibited shortcuts.
- `Done when`: observable evidence that proves completion.

For long-running work, also include measurement, realistic environment, anti-cheat rules, progress tracking, final validation, and cleanup.

## Operating Rules

- Preserve the user's original intent. Do not silently make the task easier, narrower, or different.
- Inspect relevant local context before asking questions when files, plans, tests, logs, repo state, or linked docs are safely available.
- Ask only blocking clarification questions. Prefer one high-leverage question; ask up to three when the missing facts are independent.
- If a detail is non-blocking, proceed with a conservative labeled assumption.
- Prefer measurable criteria, but do not invent fake precision.
- Keep direct `/goal` payloads under 4000 characters. If the contract needs more detail, create file-backed artifacts and make `/goal` reference `GOAL.md`.
- Add approval gates before destructive, costly, external, credentialed, production, publishing, or irreversible actions.
- Reject fake completion: weakening tests, deleting checks, hiding failures, cropping screenshots, hardcoding around validators, reducing scope without approval, or claiming production readiness from local-only evidence.

## Modes

- `quick`: output a concise goal contract in chat for bounded, low-risk work.
- `file-backed`: create `INPUT.md`, `GOAL.md`, and `STATE.md` for long-running, risky, multi-phase, production, migration, deployment, optimization, training, or resumable work.
- `audit-existing`: review an existing `/goal` draft or `GOAL.md`, identify weaknesses, and produce an improved version without deleting important constraints.

Default to `file-backed` when the direct `/goal` payload would exceed 4000 characters or the risk is unclear.

## Preflight

Before finalizing, resolve these fields or mark a conservative assumption:

| Field          | Required answer                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| Outcome        | What artifact, behavior, metric, or state must exist?                                                  |
| Done evidence  | What command, metric, screenshot, deploy, file, CI check, or review proves completion?                 |
| Scope          | What is included and excluded?                                                                         |
| Starting point | Which repo, files, plans, logs, URLs, failing checks, or environment should be inspected first?        |
| Constraints    | Are dependencies, network calls, commits, PRs, migrations, paid services, or external systems allowed? |
| Measurement    | How can progress be measured before final completion?                                                  |
| Environment    | What local, staging, preview, production-like, browser, device, or data setup is needed?               |
| Anti-cheat     | What shortcuts must not count as success?                                                              |
| Tracking       | How should progress stay visible during long runs?                                                     |
| Finalization   | What cleanup, review, tests, and report are required before completion?                                |
| Stop gates     | What conditions require asking the user instead of continuing?                                         |

Stop interviewing as soon as the contract is executable.

## Goal Quality Bar

A goal is ready only when another agent could judge honestly whether it is complete.

Weak:

```text
Make checkout faster.
```

Strong:

```text
Reduce checkout API p95 latency below 250 ms for the documented slow path, using the smallest safe server-side change. Start by inspecting `src/checkout/`, `tests/checkout/`, and the existing latency benchmark. Done when `npm run test:checkout` passes and the benchmark shows p95 below 250 ms across 3 consecutive runs. Do not remove validation, skip database calls, or weaken benchmark coverage.
```

## Measurement And Environment

Use the most honest measurement available. Bugs need reproduction and failing-to-passing evidence when possible. Tests need exact commands and pass conditions. Performance needs metric, threshold, method, environment, and run count. UI needs feature checklist, design-system adherence, screenshots, accessibility checks, and visual diff tooling when appropriate. Refactors need preserved behavior, affected modules, and validation gates. Operations need healthy state, monitoring window, rollback, and escalation trigger.

Do not validate against an environment that cannot prove the claim. Performance goals need comparable stack, flags, data shape, and runtime target. Deployment goals need deploy paths matching the real path. UI goals need the actual app rendered in a browser or device environment. Production claims require production or production-like proof unless the goal explicitly excludes it.

If the available environment is weaker than the claim, narrow the claim or add a stop gate.

## Visual Goals

Images are context, not the sole exit criteria.

Avoid:

```text
Implement this UI 100% pixel perfect from the screenshot.
```

Prefer:

```text
Implement the dashboard screen using the existing design system and the provided screenshot as visual reference. Done when the listed controls, responsive states, spacing hierarchy, accessible labels, and core interactions match the spec; verify with desktop and mobile screenshots plus the existing UI test suite.
```

If visual comparison matters, allow visual-diff tooling, but prevent the run from focusing on irrelevant asset perfection.

## Anti-Cheat

Add explicit anti-cheat clauses when relevant:

```text
Do not delete, skip, or weaken tests.
Do not hardcode around a specific fixture, transcript, screenshot, or benchmark.
Do not hide failures in logs, screenshots, reports, or CI output.
Do not crop, obscure, or selectively capture visual evidence.
Do not reduce feature scope without user approval.
Do not add fallback paths unless justified by a real runtime, compatibility, or safety need.
Do not modify production behavior only to satisfy a test.
Do not use placeholders in production code.
Do not claim production readiness from local-only evidence.
```

## Quick Output

Use this for small or medium tasks:

```text
Goal: <single concrete outcome>

Context:
- Start at <files/docs/tests/URLs/logs>.

Done when:
- <observable proof 1>
- <observable proof 2>

Scope:
- Include: <areas>
- Exclude: <non-goals>

Constraints:
- <allowed tools, dependencies, side effects, budget, approval gates>

Anti-cheat:
- <shortcuts that must not count>

Progress:
- <tracking method, or chat updates only>

Final verification:
- <commands/checks/manual review>
- <cleanup/review expectation>
```

## Codex Goal Payload

For direct goal mode, output a concise payload and verify it is under 4000 characters:

```text
/goal <concrete outcome>. Start by reading <paths>. Done when <evidence>. Scope includes <in-scope> and excludes <out-of-scope>. Constraints: <key constraints>. Anti-cheat: <fake wins forbidden>. Track progress via <method>. Final verification: <checks and cleanup>.
```

For file-backed work:

```text
/goal I have reviewed and approve /absolute/path/to/GOAL.md. Use that file as the detailed execution contract. Complete every item step by step, maintain STATE.md throughout execution, do not skip validation gates, and stop at explicit approval gates.
```

## File-Backed Artifacts

When using `file-backed` mode, create:

```text
generated-goals/YYYYMMDD-HHMMSS-<slug>/
  INPUT.md
  GOAL.md
  STATE.md
  NOTES.md optional
```

`INPUT.md` preserves the original request, mode, language, inspected context, questions, answers, and assumptions.

`GOAL.md` is the execution contract.

`STATE.md` is the checkpoint and resume ledger.

Use this `GOAL.md` section order:

```markdown
# Goal: <clear task title>

## 0. Execution Directive

## 1. Objective

## 2. Context and Starting Points

## 3. Assumptions

## 4. Scope

### In Scope

### Out of Scope

## 5. Constraints and Safety Boundaries

## 6. Anti-Cheat Rules

## 7. Required Deliverables

## 8. Execution Phases

### Phase 0: Preflight and Baseline Capture

### Phase 1: <first real phase>

### Phase N: Final Validation and Review

## 9. Measurement and Progress Tracking

## 10. Validation Matrix

## 11. Acceptance Criteria

## 12. Checkpoint and Resume Protocol

## 13. Failure Gates and Approval Gates

## 14. Final Completion Report Format
```

Each phase must include objective, checklist tasks, expected artifacts, validation checks, checkpoint update requirement, and stop condition.

Use this compact `STATE.md`:

```markdown
# State: <goal title>

Status: awaiting_human_review | ready_to_execute | in_progress | blocked | complete
Last updated: <timestamp>
Current phase: <phase>
Current branch/head: <if relevant>

## Done

- <completed checkpoint>

## Now

- <current task>

## Next

- <next task>

## Evidence

- <commands, summarized outputs, artifacts, PRs, screenshots>

## Blockers

- <blocker, owner, needed decision>

## Decisions

- <timestamp> - <decision and reason>
```

## Human Review Gate

Generated goals are review artifacts. Do not execute by default. Tell the user what to review. Surface unresolved assumptions and risks. Execution may proceed only when the user starts a separate execution request referencing the reviewed goal or explicitly approves execution.

## After Approval

If the user approves execution and a goal tool is available:

1. Call `get_goal`.
2. If no active goal exists, call `create_goal` with the approved concise objective.
3. Include verification evidence, scope, constraints, anti-cheat, and finalization.
4. Include a token budget only when the user explicitly requested one.
5. If an active goal already matches, continue it.
6. If an active goal conflicts, ask whether to finish, clear, or move the new goal to another thread.
7. Mark complete only after final verification evidence exists.
8. Mark blocked only when the same blocker has repeated across at least three goal turns and no meaningful alternative remains.

## Final Response

After refining a goal, respond with:

```text
Mode: <quick | file-backed | audit-existing>
Output: <contract or generated folder path>
Goal payload length: <N characters, must be <=4000 for direct /goal>
Assumptions: <important assumptions>
Risks: <unresolved risks or blockers>
Summary: <one paragraph>
Review: <whether execution is still gated>
Handoff: <Codex /goal payload when useful>
```

Keep the final response short. The artifact carries the detail.
