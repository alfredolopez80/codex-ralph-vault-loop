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
  - Repo-global `plan-state.json` files only gate the current session when they
    include a matching `session_id`/`sessionId`, or explicitly opt in with
    `global: true` / `applies_to_all_sessions: true`.
  - Tracks up to five blocks in `.codex/state/<session>/quality-blocks.json`
    and logs to `.codex/state/<session>/stop-hook.log`.

- `.codex/hooks/implementation_notes_guard.py`
  - Runs on `Stop`.
  - Blocks when a referenced approved plan requires implementation notes but the
    canonical repo-root notes file is missing, empty beyond the initial
    template, not approved, or present only inside an ephemeral Codex worktree.
  - Updates the canonical project implementation index after a valid plan/notes
    pair passes finalization, recording status and current commit metadata.
  - Treats hooks as guardrails only. It never writes implementation decisions.
  - Keeps RED-sensitive sessions local by skipping validation when the final
    assistant message classifies as RED.

## Context Budget Guard

The shared detector in `.codex/hooks/shared/context_budget.py` protects the
thread and Ralph memory from context-toxic payloads. It is integrated into the
existing hook chain rather than installed as a separate hook system.

- `UserPromptSubmit` via `.codex/hooks/user_prompt_capture.py`
  - Blocks inline image/base64-like prompts, huge single-line payloads, repeated
    generated replacement history, and RED-sensitive prompt material.
  - Returns only a sanitized reason; it does not echo the raw payload or persist
    the raw prompt.
- `PreToolUse` via `.codex/hooks/pre_tool_guard.py`
  - Blocks base64 encode commands, likely binary/media/database dumps, oversized
    full-file displays, high-risk broad `rg` searches over home/global runtime
    roots, and toxic patch payloads.
  - Uses `suggested_command` for bounded reads such as `sed -n '1,160p' <file>`
    instead of rewriting commands.
  - Keeps normal targeted searches and small text reads allowed.
- `PostToolUse` via `.codex/hooks/post_tool_checkpoint.py` and shared learning
  helpers
  - Skips checkpoint and learning persistence when output metadata contains
    RED-sensitive or context-toxic material.
  - Treats PostToolUse as a persistence boundary, not the primary prevention
    boundary.

The v1 guard intentionally does not add `PreCompact` or `PostCompact` behavior.
Compact lifecycle hooks should be added only after the local hook contract is
verified and covered by global install smoke tests.

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
python3 .codex/hooks/implementation_notes_guard.py < .codex/tests/fixtures/implementation-notes-no-plan.json
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
