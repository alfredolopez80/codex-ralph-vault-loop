# Hooks

Hooks provide lifecycle checks for Codex App and Codex CLI. Project hook scripts live in `.codex/hooks`, while `~/.codex/hooks.json` activates them globally.

Events:

- `SessionStart` loads compact memory.
- `UserPromptSubmit` captures safe prompt metadata.
- `PreToolUse` blocks destructive or unsafe operations.
- `PostToolUse` extracts memory candidates and records cost ledger events.
- `Stop` runs output quality checks and persists a handoff.

Hooks must degrade safely. Missing files should not crash a session. Hooks must not print secrets and must not save RED content.

Related phases: [PHASE_07](../migration/checkpoints/PHASE_07.md), [PHASE_16](../migration/checkpoints/PHASE_16.md).

