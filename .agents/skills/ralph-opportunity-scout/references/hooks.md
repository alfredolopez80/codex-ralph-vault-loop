# Lifecycle-Hook Scout

Use this reference when a repeated action should be enforced by the harness
rather than remembered by the model.

## Action Policy

Propose only. Write or modify hook config only after explicit approval. After
writing a hook, tell the user what must be reviewed or trusted in the active
Codex runtime before it can take effect.

Hooks are powerful because they run on lifecycle events. They must preserve the
repo's hook output contract, fail-open/fail-closed expectations, sandbox model,
and RED-content boundaries.

## Recognition Signals

- The user says "from now on", "every time", "always after", or "whenever".
- The same check is being manually repeated after edits or at stop time.
- The user complains about needing to remind Codex of a mechanical step.
- A safety or formatting gate should run deterministically at a lifecycle event.

## Ralph Fit

Consider hooks for:

- `SessionStart` or `UserPromptSubmit` context intake;
- `PreToolUse` or `PermissionRequest` safety checks;
- `PostToolUse` report-only observers;
- `Stop` continuation blockers when a required local condition is not met;
- `PreCompact` or `PostCompact` continuity checks.

Prefer AGENTS.md or a skill when the behavior needs judgment. Prefer a hook only
when the trigger and action are deterministic enough to be safe every time.

## Stay Inline When

- The pattern happened once.
- The action should be decided case by case.
- A wrong trigger would be more expensive than a manual reminder.
- The hook would mutate files, call external services, or persist sensitive data
  without a separate approval and safety design.

## Proposal Template

```text
Opportunity: This repeated ritual is hook-shaped.
Best Ralph path: Add a <event> lifecycle hook with <fail-open|fail-closed> behavior.
Why now: <manual repetition or deterministic trigger>.
Approval needed: Yes, before writing hook config.
Inline fallback: I will keep doing the step manually in this task.
```
