# PHASE 07 - Codex Hooks

Date: 2026-04-27
Repository: `<repo-root>`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_06.md` exists and ends with decision `PASS`.

## Scope

This phase adds Codex hook scripts under `.codex/hooks` and wires them through `.codex/hooks.json`. It also updates the global hook installer so future Codex App/CLI sessions receive the same behavior.

## Implementation

`SessionStart` runs `session_start_wakeup.py`. `UserPromptSubmit` records sanitized prompts. `PreToolUse` blocks obvious destructive commands. `PostToolUse` writes candidate learnings and a tool cost ledger. `Stop` runs the existing slop gate, then `stop_persist_memory.py` writes the latest handoff.

Shared helpers live under `.codex/hooks/shared` for paths, redaction, vault I/O, and cost policy. Hooks tolerate empty JSON input and missing optional fields.

## Validation Results

`.codex/hooks.json` parses as JSON. Every hook script executed successfully with empty JSON on stdin. `PreToolUse` blocked a destructive command fixture without printing the command. `Stop` created `handoffs/latest.md` with a temporary `RALPH_HOME`. Integration tests in `tests/integration/test_hooks_basic.py` passed with pytest.

The global installer dry-run produced valid JSON. The installer was run, and `~/.codex/hooks.json` now contains `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, and `Stop`. Secret scans over hooks, tests, and this checkpoint returned no findings.

## Risks

Hook payload schemas may differ by Codex release. The scripts use defensive key lookup and no-op behavior for missing fields, so schema drift should degrade quietly.

## Decision

PASS
