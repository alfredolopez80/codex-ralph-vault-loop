#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from implementation_index_lib import record_loose_commit, upsert_plan_entry
from implementation_notes_lib import ImplementationNotesError, resolve_for_read, resolve_roots


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the project implementation index.")
    parser.add_argument("--active-root", help="Active worktree root override.")
    parser.add_argument("--primary-root", help="Canonical local repo root override.")
    parser.add_argument("--plan", help="Canonical plan path for a planned implementation entry.")
    parser.add_argument("--notes", help="Canonical implementation notes path for a planned implementation entry.")
    parser.add_argument("--status", default="implemented", help="Plan entry status.")
    parser.add_argument("--commit", help="Commit to associate with the plan entry.")
    parser.add_argument("--branch", default="", help="Branch name override.")
    parser.add_argument("--pr", default="", help="PR URL or identifier.")
    parser.add_argument("--session-id", default="", help="Codex session id.")
    parser.add_argument("--loose-commit", help="Commit without an approved plan.")
    parser.add_argument("--reason", default="", help="Reason for a loose commit entry.")
    parser.add_argument("--entry-notes", default="", help="Short note for a loose commit entry.")
    args = parser.parse_args()

    try:
        roots = resolve_roots(args.active_root, args.primary_root)
        if args.loose_commit:
            record_loose_commit(
                primary_root=roots.primary_repo_root,
                commit=args.loose_commit,
                active_root=roots.active_worktree_root,
                reason=args.reason or "commit recorded without an approved implementation plan",
                branch=args.branch,
                notes=args.entry_notes,
            )
            print(f"IMPLEMENTATION_INDEX_LOOSE_COMMIT {args.loose_commit}")
            return 0

        if not args.plan or not args.notes:
            raise ImplementationNotesError("--plan and --notes are required unless --loose-commit is used")
        plan_path = resolve_for_read(args.plan)
        notes_path = resolve_for_read(args.notes)
        upsert_plan_entry(
            primary_root=roots.primary_repo_root,
            plan_path=plan_path,
            notes_path=notes_path,
            status=args.status,
            active_root=roots.active_worktree_root,
            commit=args.commit or "",
            branch=args.branch,
            pr=args.pr,
            session_id=args.session_id,
        )
        print(f"IMPLEMENTATION_INDEX_PLAN {plan_path}")
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_INDEX_ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
