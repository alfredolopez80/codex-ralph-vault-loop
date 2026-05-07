---
name: ralph-objective-prep
description: Prepare complex Codex objectives before native /goal execution. Use this skill when the user asks to clarify, validate, de-risk, board, or autonomously pursue a broad Goal, objective, plan, audit, recovery, or long-running coding outcome. Do not use it for simple native /goal set, status, pause, resume, complete, clear, or budget requests unless the request is ambiguous, risky, multi-phase, or needs pre-execution intake.
---

# Ralph Objective Prep

Use this skill to prepare complex objectives before Codex sets or continues a native Goal.

A native Goal is owned by Codex App or Codex CLI. This skill adds the prep layer for broad or risky work: classify the objective, remove ambiguity, record proof of success, and prepare a safe first task before native `/goal` execution continues.

This skill is a workflow and routing layer for Codex App standard. It does not register a custom UI slash command, modify Codex App UI, depend on Codex++, or add panels, badges, DOM interceptors, localStorage persistence, keyboard automation, CSS selectors, or visual controls. That UI restriction applies only to this Codex App integration; it does not restrict normal frontend, web app, dashboard, plugin, or UI work in other projects.

## Core Workflow

When the user asks to prepare, clarify, validate, de-risk, or autonomously pursue a Goal-like objective:

1. Identify the requested operation.
2. Classify the request with the Goal Complexity Classifier.
3. Use Direct Goal Pass-through Mode for simple native Goal operations.
4. Use Goal Prep Mode for complex goals before execution.
5. Never replace or shadow native `/goal`; prefer native Codex App Goal tools when they are available in the session.
6. For standard App Server clients, prefer the documented JSON-RPC methods in `references/app-server-goal-api.md`.
7. If native Goal persistence is unavailable, say so clearly and keep only a conversational fallback.
8. Never claim that a native persistent Goal was set unless the native tool or App Server request actually succeeded.

Fallback message:

```text
Native Goal persistence is unavailable in this Codex App runtime. I will keep the objective in conversation context, but it will not persist as a native thread goal.
```

## Goal Complexity Classifier

Classify before setting a new Goal or starting autonomous work. The user should not need to choose a mode.

Use Direct Goal Pass-through Mode only when all are true:

- outcome is concrete;
- scope is obvious;
- success proof is clear or safely inferable;
- risk is low;
- task is narrow;
- no discovery phase is required;
- no plan needs validation;
- no destructive action, credential, external service, or permission decision is required.

Use Goal Prep Mode when any are true:

- goal is vague or strategic;
- work is multi-phase;
- work is high risk;
- work requires discovery;
- work requires choosing implementation strategy;
- user provided a large plan that must be validated;
- success proof is ambiguous;
- task could succeed while solving the wrong problem;
- work touches many files or subsystems;
- work requires approvals, credentials, external services, or destructive actions;
- user asks for autonomy but the first safe action is unclear.

## Direct Goal Pass-through Mode

Use Direct Goal Pass-through Mode for narrow native requests such as:

- `Set goal: finish this review and report findings.`
- `Set goal: fix the failing auth unit test.`
- `Set goal budget to 50k tokens.`
- `What is the current goal?`
- `Mark goal complete.`

Behavior:

1. Defer to native `/goal` or native Goal tools when supported.
2. Normalize only when the native operation needs a short, actionable, verifiable objective sentence.
3. Do not create prep files.
4. Do not present `ralph-objective-prep` as the `/goal` command.
5. Ask for clarification only when the request is unsafe or unclear.

## Goal Prep Mode

Use Goal Prep Mode before execution for broad or ambiguous requests such as:

- `Set goal: improve this repo.`
- `Make this autonomous.`
- `Implement the whole payment flow.`
- `Follow this large plan and validate everything.`
- `Audit this branch for release risk.`

Behavior:

1. Do not execute implementation immediately.
2. Run the Intake Compiler.
3. Ask one Guided Intake question at a time only when high-impact ambiguity remains.
4. If the user says "use defaults", skip additional questions and record assumptions.
5. Create or update control files when enough context exists.
6. Set the native Goal only after the prepared charter is clear enough.
7. Continue autonomously only when there is an approved or inferable first safe task.

Default board location:

```text
~/.ralph-codex/goals/<thread-id>/<slug>/
  goal.md
  state.yaml
  notes/
```

Use a repo-local board only when the user asks or the repo documents that convention:

```text
.ralph/goals/<slug>/
  goal.md
  state.yaml
  notes/
```

Never modify `.gitignore` as part of Goal Prep unless the user explicitly asks.

## Intake Compiler

Derive these fields internally. Do not dump the full compiler output to the user by default.

```text
original_request
interpreted_outcome
input_shape: simple | vague | existing_plan | recovery | audit
audience_or_beneficiary
non_goals
hard_constraints
authority: requested | approved | inferred | needs_approval | blocked
proof_type: test | demo | artifact | metric | review | source_backed_answer | decision
completion_proof
likely_misfire
blind_spots
existing_plan_facts
```

Use the compiler output to choose Direct Goal Pass-through Mode, ask a Guided Intake question, or prepare control files.

## Guided Intake

For high-impact ambiguity, ask exactly one question at a time.

Use this shape:

```text
I read this as: <interpreted outcome>.
One possible blind spot: <risk or ambiguity>.

<question>

1. <recommended option> (Recommended) - <when it wins>
2. <second option> - <when it wins>
3. <third option if useful> - <when it wins>

My default would be <option> because <reason>.
```

Minimum ladder for vague goals:

1. Which outcome matters most?
2. What evidence proves success?
3. What is explicitly out of scope?
4. Should Codex create a control board or use native Goal only?

If the user says "use defaults", create the board with explicit assumptions instead of blocking on more questions.

## Control Files

Use the templates in `templates/` and the workflow in `references/goal-prep-flow.md`.

Control-file rules:

- `goal.md` is the human-readable charter.
- `state.yaml` is the machine-readable board state.
- `notes/` stores receipts and observations.
- Only one task should be active.
- Vague goals start with a `scout` task.
- Existing plans start with a `judge` or `pm` task.
- Audits start read-only with an `audit` task.
- `worker` tasks require `allowed_files`, `verify`, and `stop_if`.
- RED content must not be written to control files.

## Start Rules

Do not start implementation for Goal Prep Mode until:

- the interpreted outcome is concrete enough;
- authority is `requested`, `approved`, or safely `inferred`;
- the first safe task is known;
- completion proof is recorded or defaulted;
- stop rules are recorded.

If a task needs secrets, destructive actions, external credentials, or permission outside the current safe scope, stop and ask for explicit approval.

## Supported Operations

Get the current Goal when the user says:

- `what is the current goal?`
- `show goal`
- `/goal status`
- `are we still tracking a goal?`

Pause, resume, complete, or clear only when the user explicitly asks:

- `pause goal`
- `resume goal`
- `mark goal complete`
- `clear goal`

Set or update a token budget when the user asks for a budget or limit. Budgets must be positive integers. A null or omitted budget means no explicit budget.

## Safety Rules

- Do not create Goals for vague chat, emotional support, casual questions, or unrelated requests.
- Do not create active Goals for destructive filesystem actions, credential extraction, security-control bypasses, hidden background work, or actions outside the current project without explicit confirmation.
- Do not store secrets, credentials, private keys, wallet material, customer data, unsanitized logs, vault data, or RED content in a Goal or control file.
- Do not mark a Goal `complete` until the objective is actually achieved and no required work remains.
- Do not silently downgrade native persistence. If persistence is unavailable, say so.

## Response Shape

When native tooling sets a simple Goal:

```text
Goal set: <objective>
Status: active
Budget: <budget or "none">
```

When preparing a complex Goal:

```text
Goal prep started: <interpreted outcome>
Mode: prep
Next: <question or first safe task>
Board: <path or "not created yet">
```

When updating status:

```text
Goal updated: <objective>
Status: <status>
```

When clearing:

```text
Goal cleared.
```

If the runtime does not expose a supported native operation, report the limitation and use the conversational fallback instead of inventing persistence. Do not emulate `/goal` with keyboard automation, UI scraping, localStorage, or custom slash-command behavior.
