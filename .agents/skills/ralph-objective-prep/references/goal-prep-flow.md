# Goal Prep Flow

Goal Prep Mode prepares complex or ambiguous Goals before execution. It keeps one public skill, `ralph-objective-prep`, and uses an internal classifier to decide whether to defer to native Goal handling or prepare a control board first.

## Decision Flow

```text
goal request
  -> classify
      -> Direct Goal Pass-through Mode
      -> Goal Prep Mode
```

Use Direct Goal Pass-through Mode for narrow, low-risk objectives with clear proof; native `/goal` or native Goal tools own the operation.

Use Goal Prep Mode for vague, strategic, multi-phase, high-risk, plan-based, audit, recovery, or autonomous work where the first safe action or completion proof is unclear.

## Prep Sequence

1. Compile intake fields.
2. Ask one guided question if a high-impact ambiguity remains.
3. If the user says "use defaults", record assumptions and continue.
4. Choose board location.
5. Create `goal.md`, `state.yaml`, and `notes/`.
6. Set or update the native Goal only when the prepared charter is clear enough; never emulate `/goal` as a custom command.
7. Start only the first safe task.

## Board Location

Default:

```text
~/.ralph-codex/goals/<thread-id>/<slug>/
```

Use repo-local storage only when explicitly requested or documented by the repo:

```text
.ralph/goals/<slug>/
```

Do not edit `.gitignore` by default.

## Task Type Guidance

- `scout`: discovery, repo inspection, source-of-truth lookup.
- `judge`: validate a plan or decision before implementation.
- `worker`: execute scoped implementation with known files and verification.
- `pm`: decompose a large plan into phases and gates.
- `audit`: read-only review for risk, correctness, or release readiness.

## Receipts

Receipts should point to evidence, not secrets. Examples:

- command names and pass/fail summaries;
- file paths changed;
- test names;
- review findings;
- user decisions;
- rollback notes.

Never store RED content in control files or receipts.
