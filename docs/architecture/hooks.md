# Hooks

Hooks provide lifecycle checks for Codex App and Codex CLI. Project hook scripts live in `.codex/hooks`, while `~/.codex/hooks.json` activates them globally.

Events:

- `SessionStart` loads compact memory.
- `UserPromptSubmit` captures safe prompt metadata.
- `PreToolUse` blocks destructive or unsafe operations.
- `PostToolUse` runs through the consolidated `post_tool_dispatch.py`, which gates the existing line, shaping, memory, checkpoint, advisor, and ledger policies by tool/result class.
- `Stop` runs through the single `stop_dispatch.py` reducer. It evaluates scoped objective evidence, preserves the file-line and implementation-notes hard gates, records route and phrase observations as report-only telemetry, writes a lightweight handoff, and enforces one bounded continuation budget. Heavy memory promotion is marked for later processing and is not run on the critical path.

The file-line guard is intentionally blocking for source-like files and intentionally permissive for generated artifacts such as lockfiles, minified assets, maps, and media. When it blocks, Codex must split the file before continuing. The required split style is behavior-preserving and boundary-oriented: tests before and after, domain/use-case/component boundaries, no generic dumping-ground modules, validation/auth/secrets and trust boundaries preserved, sec-context anti-patterns avoided while moving code, and React/Next splits aligned with component-per-file, extracted hooks, direct imports, and lazy loading for heavy UI.

Hooks must degrade safely. Missing files should not crash a session. Hooks must not print secrets and must not save RED content.
For `Stop`, allow/report-only paths must leave stdout empty; only blocking paths emit `{"decision":"block","reason":"..."}`.
For `PostToolUse`, report-only paths must also leave stdout empty. `decision:"warn"` is not a supported Codex hook response and is persisted to local JSONL reports instead.

The shaping ripple hook is warn-only by default. It checks touched Markdown files for `shaping: true` frontmatter and emits a generic checklist to keep related shaping artifacts synchronized. It does not print document contents. Set `RALPH_SHAPING_RIPPLE_STRICT=1` to make the reminder blocking.

The consolidated PostToolUse dispatcher keeps bounded, project-scoped dedupe
and metrics in the Ralph runtime. Its key uses session, turn, and tool-use
identity (including the parent identity of `write_stdin` polls), with a short
TTL and bounded entry count. Corrupt state is quarantined and operational
state failures remain fail-open. Repeating one tool-use identity does not
duplicate candidates, checkpoints, or ledger records.

The consolidated Stop dispatcher keeps state under the project-scoped Ralph
runtime. It emits a block only for current, scoped objective evidence such as a
failed required test, a missing required file, a file-line violation, an
invalid required implementation-notes pair, or a pending task state. Narrative
phrases, missing route markers, stale or foreign state, and pending promotion
are report-only. `stop_hook_active=true` allows immediately. The budget reserves
a continuation atomically before emitting it, permits one ordinary continuation
and one additional continuation only for a new critical evidence fingerprint,
then allows Stop with a local exhaustion warning.

Related phases: [PHASE_07](../migration/checkpoints/PHASE_07.md), [PHASE_16](../migration/checkpoints/PHASE_16.md).
