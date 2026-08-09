---
name: ralph-plan-implementation-notes
description: Maintain canonical approved-plan notes, indexes, provenance, and consolidation gates.
---

# Ralph plan implementation notes

Use this skill when a user approves a plan and requests implementation, or
when a finalization gate references implementation notes. The canonical copy
belongs under the primary repository root `.ralph/plans/`; a secondary
worktree copy is only a disposable convenience.

## Operating procedure

1. Confirm plan approval and whether notes are required. Do not create durable
   notes for an unapproved plan.
2. Create notes with `scripts/plans/create-implementation-notes.py`, using
   `--active-root` and `--primary-root` when working in a temporary worktree.
3. Append timestamped decisions, deviations, tradeoffs, open questions, and
   validation findings with `append-implementation-note.py`.
4. Update the project implementation index and consolidate only through the
   dry-run then apply workflow.
5. Verify canonical-root ownership, path containment, symlink safety, a
   non-initial entry, sanitization, and current commit metadata.

## References

- Full workflow: `docs/plans/implementation-notes.md`.
- Creation: `scripts/plans/create-implementation-notes.py`.
- Append and index: `scripts/plans/append-implementation-note.py` and
  `scripts/plans/update-implementation-index.py`.
- Finalization gate: `.codex/hooks/implementation_notes_guard.py`.

## Required validation

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_implementation_notes_workflow.py tests/integration/test_implementation_notes_consolidation.py tests/integration/test_implementation_notes_consolidation_security.py tests/integration/test_global_implementation_notes_e2e.py -q
```
