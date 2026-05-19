#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from implementation_notes_lib import (
    ImplementationNotesError,
    ensure_not_red,
    ensure_plan_path_allowed,
    html_document,
    infer_title,
    is_codex_worktree,
    is_plan_approved,
    now_local,
    parse_plan_metadata,
    resolve_for_read,
    resolve_notes_path_for_plan,
    resolve_roots,
    run_git,
    sync_plan_to_primary,
    write_implementation_plan_state,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create per-plan implementation notes HTML.")
    parser.add_argument("--plan", required=True, help="Approved plan path.")
    parser.add_argument("--notes", help="Optional notes output path.")
    parser.add_argument("--active-root", help="Active worktree root override.")
    parser.add_argument("--primary-root", help="Canonical local repo root override.")
    parser.add_argument("--approved", action="store_true", help="Treat the current user turn as explicit plan approval.")
    parser.add_argument("--allow-docs", action="store_true", help="Allow sanitized output under docs/ instead of .ralph/plans/.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing plan/notes when safe.")
    args = parser.parse_args()

    try:
        plan_path = resolve_for_read(args.plan)
        roots = resolve_roots(args.active_root, args.primary_root)
        ensure_plan_path_allowed(plan_path, roots)
        metadata = parse_plan_metadata(plan_path)
        if not is_plan_approved(metadata, explicit_approved=args.approved):
            raise ImplementationNotesError("plan is not approved; set Plan approval status: approved or pass --approved")
        notes_path = resolve_notes_path_for_plan(
            metadata,
            plan_path,
            roots.primary_repo_root,
            explicit_notes=Path(args.notes).expanduser() if args.notes else None,
            allow_docs=args.allow_docs,
        )
        if is_codex_worktree(notes_path):
            raise ImplementationNotesError("refusing to create the only durable notes copy under ~/.codex/worktrees")
        if notes_path.exists() and not args.force:
            raise ImplementationNotesError(f"notes already exist: {notes_path}")
        canonical_plan = sync_plan_to_primary(plan_path, roots.primary_repo_root, notes_path, force=args.force)

        timestamp = now_local()
        session_id = os.environ.get("CODEX_SESSION_ID") or os.environ.get("RALPH_SESSION_ID") or "unknown"
        git_sha = run_git(roots.active_worktree_root, "rev-parse", "HEAD")
        git_branch = run_git(roots.active_worktree_root, "branch", "--show-current") or run_git(
            roots.active_worktree_root, "rev-parse", "--abbrev-ref", "HEAD"
        )
        html = html_document(
            title=f"Implementation Notes - {infer_title(canonical_plan)}",
            plan_path=canonical_plan,
            notes_path=notes_path,
            roots=roots,
            git_sha=git_sha,
            git_branch=git_branch,
            session_id=session_id,
            timestamp=timestamp,
        )
        ensure_not_red("generated implementation notes", html)
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text(html, encoding="utf-8")
        write_implementation_plan_state(roots, session_id, canonical_plan, notes_path)
        print(f"IMPLEMENTATION_NOTES_CREATED {notes_path}")
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_NOTES_ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
