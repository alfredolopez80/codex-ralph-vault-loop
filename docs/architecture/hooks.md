# Hooks

Hooks provide lifecycle checks for Codex App and Codex CLI. Project hook scripts live in `.codex/hooks`, while `~/.codex/hooks.json` activates them globally.

Events:

- `SessionStart` loads compact memory.
- `UserPromptSubmit` captures safe prompt metadata.
- `PreToolUse` blocks destructive or unsafe operations.
- `PostToolUse` blocks touched non-generated files over 350 lines, warns on `shaping: true` Markdown files that may need ripple checks, extracts memory candidates, and records cost ledger events, including route-family metadata.
- `Stop` rescans changed git files for the same 350-line guard, runs output quality checks, records report-only route warnings when non-trivial work lacks a visible `ROUTE_DECISION`, and persists a handoff.

The file-line guard is intentionally blocking for source-like files and intentionally permissive for generated artifacts such as lockfiles, minified assets, maps, and media. When it blocks, Codex must split the file before continuing. The required split style is behavior-preserving and boundary-oriented: tests before and after, domain/use-case/component boundaries, no generic dumping-ground modules, validation/auth/secrets and trust boundaries preserved, sec-context anti-patterns avoided while moving code, and React/Next splits aligned with component-per-file, extracted hooks, direct imports, and lazy loading for heavy UI.

Hooks must degrade safely. Missing files should not crash a session. Hooks must not print secrets and must not save RED content.
For `Stop`, allow/report-only paths must leave stdout empty; only blocking paths emit `{"decision":"block","reason":"..."}`.

The shaping ripple hook is warn-only by default. It checks touched Markdown files for `shaping: true` frontmatter and emits a generic checklist to keep related shaping artifacts synchronized. It does not print document contents. Set `RALPH_SHAPING_RIPPLE_STRICT=1` to make the reminder blocking.

Related phases: [PHASE_07](../migration/checkpoints/PHASE_07.md), [PHASE_16](../migration/checkpoints/PHASE_16.md).
