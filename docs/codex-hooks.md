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

- `.codex/hooks/user_prompt_improve.py`
  - Runs on every non-empty `UserPromptSubmit` after safe prompt capture and
    before continuity/memory context.
  - Injects a compact, non-authoritative `Improve Prompt Contract` that frames
    the request as goal, success evidence, constraints, tools, output, and stop
    rules.
  - Preserves the user's task type, explicit values, language, permissions, and
    scope. It never widens authorization or exposes a rewritten prompt unless
    the user asks for one.
  - Does not echo or persist the raw prompt and fails open on local runtime
    errors. Empty prompts produce no stdout.

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
  - The next hook, `user_prompt_improve.py`, receives the same event but emits
    only its static improvement contract; the user's content is not copied into
    the injected context.
- `PreToolUse` via `.codex/hooks/pre_tool_guard.py`
  - Blocks base64 encode commands, likely binary/media/database dumps, oversized
    full-file displays, high-risk broad `rg` searches over home/global runtime
    roots, and toxic patch payloads.
  - Uses `suggested_command` for bounded reads such as `sed -n '1,160p' <file>`
    instead of rewriting commands.
  - Keeps normal targeted searches and small text reads allowed.
  - Allows static `apply_patch` envelopes that only create or update untracked
    `.local-notes` artifacts. Creation is not treated as execution.
  - Requires an explicit static `--context` on every `kubectl` command and
    verifies whether that context belongs to a running minikube profile with a
    matching API endpoint.
  - Allows ordinary mutations and resource deletion in verified minikube;
    complete namespace, cluster, manifest-set, or `--all` deletion still needs
    one exact human approval.
  - Inspects cloud commands in scripts identically regardless of script path.
    Approval hashes include the script content hash, so later edits invalidate
    approval. The canonical minikube runner prints the verified profile and
    context before execution.
- `PostToolUse` via `.codex/hooks/post_tool_checkpoint.py` and shared learning
  helpers
  - Skips checkpoint and learning persistence when output metadata contains
    RED-sensitive or context-toxic material.
  - Treats PostToolUse as a persistence boundary, not the primary prevention
    boundary.

The v1 guard intentionally does not add `PreCompact` or `PostCompact` behavior.
Compact lifecycle hooks should be added only after the local hook contract is
verified and covered by global install smoke tests.

## AutoResearch Observer

AutoResearch hook support is deliberately cheap. Hooks may observe bounded
`METRIC name=value` output when a valid AutoResearch session is active, but they
must not run benchmarks, Git scans, external models, MCP tools, or synthesis.
Pending observations are written under the project-scoped Ralph runtime path:

```text
~/.ralph-codex/projects/<project_id>/autoresearch/pending-metrics.jsonl
```

Runtime paths are normalized and constrained, symlink escapes are rejected, and
new observation files use restrictive permissions with single-call atomic append
writes. Set
`RALPH_AUTORESEARCH_OBSERVER=0` to disable observer writes.

## Hook Timing And Responsibility

| Timing                   | Hook event / surface                                                                                       | Responsibility                                                                                                                                                                      | Validation evidence                                                                                                                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Session start            | `SessionStart` / `session_start_wakeup.py`                                                                 | Run dream catch-up when due, then Ralph wakeup for the active project.                                                                                                              | `bash scripts/setup/doctor-global.sh`; `python3 scripts/setup/smoke-global-hooks.py` after install.                                                                                                          |
| Before prompt context    | `UserPromptSubmit` / classifier, `user_prompt_capture.py`, `user_prompt_improve.py`, continuity and recall | Classify complexity and sensitivity, reject unsafe prompt payloads, inject the compact Improve Prompt contract, then add scoped continuity/memory as non-authoritative context.     | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_hook_config_lockstep.py tests/integration/test_hooks_basic.py -q`; `bash .codex/tests/run-hook-tests.sh`.                         |
| Before command execution | `PreToolUse` / `pre_tool_guard.py`                                                                         | Enforce SFW and RED boundaries; require explicit Kubernetes context; verify minikube destination; evaluate scripts independently of location; gate complete or non-local mutations. | `bash .codex/tests/run-hook-tests.sh`; focused nested-envelope and cloud-command gate tests.                                                                                                                 |
| After command execution  | `PostToolUse` / `post_tool_checkpoint.py`, `post_tool_extract_memory.py`, `autoresearch_observer.py`       | Skip RED or context-toxic persistence; capture bounded AutoResearch metrics only when an active session exists.                                                                     | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_hooks_basic.py -q`; `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_autoresearch_hook_observer.py -q`. |
| Thread finalization      | `Stop` hooks and `implementation_notes_guard.py`                                                           | Enforce quality gates, safe handoff, route warnings, and approved-plan implementation notes.                                                                                        | `bash .codex/tests/run-hook-tests.sh`; implementation-notes integration tests.                                                                                                                               |
| Compact lifecycle        | `PreCompact` / `PostCompact`                                                                               | Deferred; no productivity pattern may assume compact hook enforcement.                                                                                                              | Documented deferral until install/doctor/smoke coverage exists.                                                                                                                                              |
| Weekly validation        | Codex App automation                                                                                       | Friday 10:00 AM report-only AutoResearch validation; no global-flow mutation without user approval.                                                                                 | Automation report, dirty-state before/after, and deterministic AutoResearch eval outputs.                                                                                                                    |

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
python3 .codex/hooks/user_prompt_improve.py < .codex/tests/fixtures/user-prompt-complex.json
bash .codex/hooks/anti-rationalization-stop.sh < .codex/tests/fixtures/stop-excuse.json
bash .codex/hooks/ralph-stop-quality-gate.sh < .codex/tests/fixtures/stop-verified.json
python3 .codex/hooks/implementation_notes_guard.py < .codex/tests/fixtures/implementation-notes-no-plan.json
```

Hooks that write to stdout must print valid JSON. `Stop` hooks block with:

```json
{ "decision": "block", "reason": "..." }
```

They allow stop by writing nothing to stdout. Report-only Stop findings, such
as routing or vault-review reminders, are persisted to local reports or JSONL
ledgers instead of emitting `decision:warn`.

## Output Contract

The active contract follows the official Codex hooks docs at
`https://developers.openai.com/codex/hooks`.

| Event              | Ralph stdout contract                                                                                                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SessionStart`     | Empty stdout, plain text context, or JSON with common fields / `hookSpecificOutput.additionalContext`.                                                                                                       |
| `UserPromptSubmit` | Empty stdout, plain text context, JSON `hookSpecificOutput.additionalContext`, or blocking JSON `{"decision":"block","reason":"..."}`.                                                                       |
| `PreToolUse`       | Empty stdout for allow. Blocking uses `hookSpecificOutput.permissionDecision="deny"` or legacy `{"decision":"block","reason":"..."}`. Do not emit `continue`, `stopReason`, or `suppressOutput`.             |
| `PostToolUse`      | Empty stdout for report-only observers. Blocking/feedback uses `{"decision":"block","reason":"..."}` or `continue:false` with a reason. Do not emit `decision:"warn"`, `continue:true`, or `suppressOutput`. |
| `Stop`             | Empty stdout for allow/report-only. JSON stdout must be valid and should only be `{"decision":"block","reason":"..."}` when asking Codex to continue.                                                        |

Operational hooks should fail open for persistence errors. If a JSONL ledger,
checkpoint, vault report, or local memory file is unavailable or corrupt, the
hook must return exit code `0` and either recover local state or skip the
write. Guardrail hooks may still block intentionally with supported JSON.

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
