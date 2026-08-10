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

`progress.py context` is the public recovery surface. Its pure renderer uses a
valid new `state.json` first, a single bounded legacy HTML parse only at a
recovery boundary, and no automatic selection when active plans are ambiguous.
Use `--event ordinary|startup|resume|compact|clear|reset|external|explicit`,
an explicit `--session-id`, and `--context-epoch` when exercising lifecycle
semantics. The content-free emission ledger is written only for a real
non-empty capsule; hits are read-only. The consolidated `UserPromptSubmit`
and `SessionStart` dispatchers now consume this engine through a local,
cache-first bridge. The legacy fallback remains feature-flagged with
`RALPH_PROGRESS_LEGACY_FALLBACK=1`; compatibility wrappers and old checkpoint
readers are evidence only and are not independent progress implementations.

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

## Store and safety contract

The CLI writes only the canonical primary-checkout store under
`.local-notes/ralph/implementation/`; a linked worktree is never selected as a
write root. All plan IDs, state snapshots, journals, context-ledger rows,
exports, diagnostics, and hook responses are size-bounded. Store and runtime
writers use private modes, no-follow descriptors, regular/non-aliased-file
checks, complete-write loops, atomic same-directory publication, and directory
`fsync`. A target that changes between validation and publication is an
unknown/blocked result, not a success claim.

Mutating replay rejects an incomplete JSONL tail. Current-schema corruption is
preserved for explicit recovery; a future schema is a hard block and is never
quarantined, downgraded, or overwritten. Operation IDs are plan-scoped:
identical retries are no-ops, while changed material payloads conflict. Hash
chains provide local integrity evidence but are not signatures. Approval is
read from the canonical plan document, not a payload boolean. Automatic plan
selection is limited to the active repository's main checkout and one
unambiguous active plan; ambiguous, foreign, symlinked, hardlinked, or
cross-worktree sources are rejected.

The progress-maintenance path is permanently local for this contract: it has
zero Terra/Sol/advisor/worker/MCP allowance. Model fields are content-free
platform provenance labels and do not attest to an executor. Legacy HTML,
Markdown, index, and consolidated views are explicit `export`, migration, or
rollback outputs only; hooks and Stop never publish them implicitly. The
bounded report/observability readers reject raw bodies and cap files, records,
groups, quarantine lines, and serialized output.

## References

- Full workflow: `docs/plans/implementation-notes.md`.
- Creation: `scripts/plans/create-implementation-notes.py`.
- Append and index: `scripts/plans/append-implementation-note.py` and
  `scripts/plans/update-implementation-index.py`.
- Finalization gate: `.codex/hooks/implementation_notes_guard.py`.
- Recovery engine: `scripts/plans/progress_context.py`.

## Required validation

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_progress_cli.py tests/integration/test_implementation_notes_workflow.py tests/integration/test_implementation_notes_consolidation.py tests/integration/test_implementation_notes_consolidation_security.py tests/integration/test_global_implementation_notes_e2e.py -q
```
