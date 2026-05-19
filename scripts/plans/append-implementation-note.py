#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from implementation_notes_lib import (
    ALLOWED_CATEGORIES,
    ImplementationNotesError,
    append_entry,
    entry_html,
    ensure_not_red,
    is_codex_worktree,
    now_local,
    resolve_for_write,
    resolve_roots,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a timestamped implementation note entry.")
    parser.add_argument("--notes", required=True, help="Implementation notes HTML path.")
    parser.add_argument("--category", required=True, choices=sorted(ALLOWED_CATEGORIES))
    parser.add_argument("--decision", required=True)
    parser.add_argument("--reason", default="")
    parser.add_argument("--impact", default="")
    parser.add_argument("--related-file", action="append", default=[])
    parser.add_argument("--status", default="active")
    parser.add_argument("--active-root", help="Active worktree root override.")
    parser.add_argument("--primary-root", help="Canonical local repo root override.")
    parser.add_argument("--allow-docs", action="store_true")
    args = parser.parse_args()

    try:
        roots = resolve_roots(args.active_root, args.primary_root)
        notes_path = resolve_for_write(args.notes, roots.primary_repo_root, allow_docs=args.allow_docs)
        if is_codex_worktree(notes_path):
            raise ImplementationNotesError("refusing to append to a worktree-only notes path under ~/.codex/worktrees")
        if not notes_path.exists():
            raise ImplementationNotesError(f"notes file does not exist: {notes_path}")
        ensure_not_red("implementation note entry", "\n".join([args.decision, args.reason, args.impact, *args.related_file, args.status]))
        entry = entry_html(
            category=args.category,
            decision=args.decision,
            reason=args.reason,
            impact=args.impact,
            related_files=args.related_file,
            status=args.status,
            timestamp=now_local(),
        )
        ensure_not_red("rendered implementation note entry", entry)
        append_entry(notes_path, entry, args.category)
        print(f"IMPLEMENTATION_NOTE_APPENDED {notes_path}")
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_NOTES_ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
