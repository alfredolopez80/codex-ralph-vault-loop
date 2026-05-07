# Codex App Server Goal API

This reference documents the standard Codex App Server Goal surface verified from the local experimental protocol schema.

The `global-goal` skill must treat this as a standard persistence surface, not as a custom Codex++ UI integration.

## Feature Status

The `goals` feature may be marked `under development` and may be disabled in a runtime. If the runtime does not expose Goal persistence, Codex should use the conversational fallback described in `SKILL.md`.

## Transport

`codex app-server` supports standard transports such as:

- `stdio://`
- `unix://`
- `unix://PATH`
- `ws://IP:PORT`
- `off`

`codex app-server proxy` can proxy stdio bytes to a running app-server control socket when that socket exists. A missing default socket is a transport limitation, not a failure of the skill.

## Methods

### `thread/goal/set`

Sets a new Goal or updates fields on an existing Goal.

Params:

```json
{
  "threadId": "thr_...",
  "objective": "Finish the implementation and verify tests pass.",
  "status": "active",
  "tokenBudget": 100000
}
```

Rules:

- `threadId` is required.
- `objective` may be a string or null.
- `status` may be a supported Goal status or null.
- `tokenBudget` may be an integer or null at protocol level.
- Skill policy should only request positive integers when setting a budget.

Response:

```json
{
  "goal": {
    "threadId": "thr_...",
    "objective": "Finish the implementation and verify tests pass.",
    "status": "active",
    "tokenBudget": 100000,
    "tokensUsed": 0,
    "timeUsedSeconds": 0,
    "createdAt": 1760000000,
    "updatedAt": 1760000000
  }
}
```

### `thread/goal/get`

Gets the current Goal for a thread.

Params:

```json
{
  "threadId": "thr_..."
}
```

Response when a Goal exists:

```json
{
  "goal": {
    "threadId": "thr_...",
    "objective": "Finish the implementation and verify tests pass.",
    "status": "active",
    "tokenBudget": 100000,
    "tokensUsed": 1234,
    "timeUsedSeconds": 60,
    "createdAt": 1760000000,
    "updatedAt": 1760000060
  }
}
```

Response when no Goal exists:

```json
{
  "goal": null
}
```

### `thread/goal/clear`

Clears the current Goal for a thread.

Params:

```json
{
  "threadId": "thr_..."
}
```

Response:

```json
{
  "cleared": true
}
```

## Events

### `thread/goal/updated`

Emitted when a Goal changes.

Payload:

```json
{
  "threadId": "thr_...",
  "turnId": null,
  "goal": {
    "threadId": "thr_...",
    "objective": "Finish the implementation and verify tests pass.",
    "status": "active",
    "tokenBudget": 100000,
    "tokensUsed": 0,
    "timeUsedSeconds": 0,
    "createdAt": 1760000000,
    "updatedAt": 1760000000
  }
}
```

### `thread/goal/cleared`

Emitted when a Goal is cleared.

Payload:

```json
{
  "threadId": "thr_..."
}
```

## Types

`ThreadGoalStatus`:

- `active`
- `paused`
- `budgetLimited`
- `complete`

`ThreadGoal` fields:

- `threadId`
- `objective`
- `status`
- `tokenBudget`
- `tokensUsed`
- `timeUsedSeconds`
- `createdAt`
- `updatedAt`
