---
name: ralph-plan-implementation-notes
description: Maintain canonical approved-plan notes, indexes, provenance, and consolidation gates.
---

# Ralph plan implementation notes

The public implementation-progress surface is the deterministic CLI:

```text
scripts/plans/progress.py
```

The canonical business state is written only through the new implementation
store. Normal progress work uses `start`, `record`, `phase`, `validate`,
`status`, `context`, `export`, and `verify`; `migrate-legacy` and
`rebuild-legacy` are explicit maintenance commands and never run implicitly.
The CLI makes no model, network, MCP, advisor, or worker calls. JSON output is
available with `--json` or `--format json`, errors use stable codes, and views
are persisted only at an explicit output/rebuild boundary.

Use this skill when a user approves a plan and requests implementation, or
when a finalization gate references implementation notes. The canonical copy
belongs under the primary repository root `.ralph/plans/`; a secondary
worktree copy is only a disposable convenience.

## Operating procedure

1. Confirm plan approval and whether notes are required before any intentional
   legacy compatibility export. The new store itself does not create HTML.
2. Start a plan with `python3 scripts/plans/progress.py start --plan <path>`.
3. Record material state with `record`, `phase`, and `validate`, passing an
   explicit `--operation-id` whenever a caller may retry the command.
4. Read with `status`, `context`, or `verify`; export views only when a human
   explicitly requests `export --output <path>` or `rebuild-legacy`.
5. Run `migrate-legacy --dry-run` before a separately authorized apply. The
   command preserves legacy files and imports through the new store API.

The four historical scripts remain compatibility evidence for existing hook
and workflow tests. Their legacy behavior is bounded and explicit: the create
wrapper selects it when a legacy-only option (`--notes`, `--approved`,
`--active-root`, `--primary-root`, `--allow-docs`, or `--force`) is present;
the append, context-reader, and index scripts retain their old option surface
only as compatibility entrypoints. They are not lifecycle writers for the new
store and must not be invoked by new hooks.

## References

- Full workflow: `docs/plans/implementation-notes.md`.
- Creation: `scripts/plans/create-implementation-notes.py`.
- Append and index: `scripts/plans/append-implementation-note.py` and
  `scripts/plans/update-implementation-index.py`.
- Finalization gate: `.codex/hooks/implementation_notes_guard.py`.

## Required validation

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_progress_cli.py tests/integration/test_implementation_notes_workflow.py tests/integration/test_implementation_notes_consolidation.py tests/integration/test_implementation_notes_consolidation_security.py tests/integration/test_global_implementation_notes_e2e.py -q
```
