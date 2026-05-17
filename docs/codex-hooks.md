# Codex Ralph Hooks

This repository registers Codex-native hooks in `.codex/hooks.json`. The hooks
use the official Codex event schema, write local state under `.codex/state/`,
and avoid Claude-only concepts such as `matcher` on `UserPromptSubmit` and
`Stop`.

## Hooks

- `.codex/hooks/universal-prompt-classifier.sh`
  - Runs on `UserPromptSubmit`.
  - Classifies prompt complexity from 1 to 10.
  - Routes prompts as `DIRECT`, `QUICK_ARISTOTLE`, `PLAN_REQUIRED`, or
    `DECOMPOSE_AND_VALIDATE`.
  - Stores `.codex/state/<session>/prompt-classification.json`.
  - Adds concise `additionalContext` without blocking simple prompts.

- `.codex/hooks/aristotle-analysis-display.sh`
  - Runs on `UserPromptSubmit` after classification.
  - For complexity 3, injects a short first-principles reminder.
  - For complexity 4 or higher, injects the five Aristotle phases and asks for
    a verifiable plan before file edits when the route requires it.
  - For complexity 1 or 2, returns `{"continue":true}` without extra context.

- `.codex/hooks/anti-rationalization-stop.sh`
  - Runs on `Stop`.
  - Allows immediately when `stop_hook_active == true`.
  - Blocks excuse or fake-done language unless the message or safe transcript
    tail includes factual verification evidence.
  - Tracks up to three blocks in `.codex/state/<session>/anti-rat-blocks.json`,
    then allows stop to prevent loops.

- `.codex/hooks/ralph-stop-quality-gate.sh`
  - Runs on `Stop`.
  - Allows immediately when `stop_hook_active == true`.
  - Checks Ralph/Codex state files for `verified_done`, active loops, failed
    quality gates, pending tasks, and missing validation.
  - Tracks up to five blocks in `.codex/state/<session>/quality-blocks.json`
    and logs to `.codex/state/<session>/stop-hook.log`.

## Manual Tests

Run the local hook smoke suite:

```bash
bash .codex/tests/run-hook-tests.sh
```

The runner sets `CODEX_HOOK_STATE_ROOT` to a temporary directory so tests do not
need to write generated session files into `.codex/state/`. Normal Codex runs do
not set that variable and continue to use `.codex/state/<session>`.
The override is accepted only when it is an absolute path.

Run a single hook by piping a fixture:

```bash
bash .codex/hooks/universal-prompt-classifier.sh < .codex/tests/fixtures/user-prompt-complex.json
bash .codex/hooks/aristotle-analysis-display.sh < .codex/tests/fixtures/user-prompt-complex.json
bash .codex/hooks/anti-rationalization-stop.sh < .codex/tests/fixtures/stop-excuse.json
bash .codex/hooks/ralph-stop-quality-gate.sh < .codex/tests/fixtures/stop-verified.json
```

Every hook should print valid JSON. `Stop` hooks block with:

```json
{ "decision": "block", "reason": "..." }
```

They allow stop with:

```json
{ "continue": true, "stopReason": "..." }
```

## Trusting Hooks In Codex

Use `/hooks` in Codex to review and trust the commands registered in
`.codex/hooks.json`. The new commands are rooted through Git:

```text
bash "$(git rev-parse --show-toplevel)/.codex/hooks/<script>.sh"
```

## Temporary Disable

To disable these hooks temporarily, remove or comment the relevant command
entries in `.codex/hooks.json`, or move the script path out of the registered
event while testing. Restore the entries before relying on Ralph gate behavior.

## Reset State

Hook state is local and ignored by Git. To reset it, delete generated session
directories under `.codex/state/` while keeping `.codex/state/.gitignore`.

For isolated manual tests, set `CODEX_HOOK_STATE_ROOT` to any writable scratch
directory before invoking hooks.

Do not persist secrets, transcripts, or raw prompts in `.codex/state/`.
