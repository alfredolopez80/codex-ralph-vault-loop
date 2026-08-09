"""Bounded compatibility implementations for the pre-Phase-4 scripts.

This module is intentionally not imported by hooks or by normal progress
operations.  It is the single legacy implementation used by the four thin
script adapters while reader-first migration evidence remains supported.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from implementation_context import render_implementation_context, select_implementation_context
from implementation_index_lib import (
    ALLOWED_EVENTS,
    append_note_and_refresh,
    current_git_metadata,
    load_index,
    record_loose_commit,
    upsert_plan_entry,
    validate_plan_notes_ownership,
)
from implementation_notes_lib import (
    ALLOWED_CATEGORIES,
    ImplementationNotesError,
    ensure_not_red,
    ensure_plan_path_allowed,
    entry_html,
    html_document,
    infer_title,
    is_codex_worktree,
    is_plan_approved,
    now_local,
    parse_plan_metadata,
    resolve_for_read,
    resolve_for_write,
    resolve_notes_path_for_plan,
    resolve_roots,
    sync_plan_to_primary,
    write_implementation_plan_state,
)


def create(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create per-plan implementation notes HTML.")
    parser.add_argument("--compat-legacy", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--plan", required=True, help="Approved plan path.")
    parser.add_argument("--notes", help="Optional notes output path.")
    parser.add_argument("--active-root", help="Active worktree root override.")
    parser.add_argument("--primary-root", help="Canonical local repo root override.")
    parser.add_argument("--approved", action="store_true", help="Treat the current user turn as explicit plan approval.")
    parser.add_argument("--allow-docs", action="store_true", help="Allow sanitized output under docs/ instead of .ralph/plans/.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing plan/notes when safe.")
    args = parser.parse_args(argv)

    try:
        plan_path = resolve_for_read(args.plan)
        roots = resolve_roots(args.active_root, args.primary_root)
        load_index(roots.primary_repo_root, quarantine_corrupt=False)
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
        validate_plan_notes_ownership(
            primary_root=roots.primary_repo_root,
            plan_path=plan_path,
            notes_path=notes_path,
        )
        if notes_path.exists() and not args.force:
            raise ImplementationNotesError(f"notes already exist: {notes_path}")
        git_meta = current_git_metadata(roots.active_worktree_root)
        canonical_plan = sync_plan_to_primary(plan_path, roots.primary_repo_root, notes_path, force=args.force)
        timestamp = now_local()
        session_id = os.environ.get("CODEX_SESSION_ID") or os.environ.get("RALPH_SESSION_ID") or "unknown"
        html = html_document(
            title=f"Implementation Notes - {infer_title(canonical_plan)}",
            plan_path=canonical_plan,
            notes_path=notes_path,
            roots=roots,
            git_sha=git_meta["commit"],
            git_branch=git_meta["branch"],
            session_id=session_id,
            timestamp=timestamp,
        )
        ensure_not_red("generated implementation notes", html)
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text(html, encoding="utf-8")
        write_implementation_plan_state(roots, session_id, canonical_plan, notes_path)
        upsert_plan_entry(
            primary_root=roots.primary_repo_root,
            plan_path=canonical_plan,
            notes_path=notes_path,
            status="active",
            active_root=roots.active_worktree_root,
            session_id=session_id,
            event="notes_created",
        )
        print(f"IMPLEMENTATION_NOTES_CREATED {notes_path}")
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_NOTES_ERROR {exc}", file=sys.stderr)
        return 1


def append(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Append a timestamped implementation note entry.")
    parser.add_argument("--compat-legacy", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--notes", required=True, help="Implementation notes HTML path.")
    parser.add_argument("--category", required=True, choices=sorted(ALLOWED_CATEGORIES))
    parser.add_argument("--decision", required=True)
    parser.add_argument("--reason", default="")
    parser.add_argument("--impact", default="")
    parser.add_argument("--related-file", action="append", default=[])
    parser.add_argument("--status", default="active")
    parser.add_argument("--operation-id", help="Stable operation id for retry-safe event deduplication.")
    parser.add_argument("--active-root", help="Active worktree root override.")
    parser.add_argument("--primary-root", help="Canonical local repo root override.")
    parser.add_argument("--allow-docs", action="store_true")
    args = parser.parse_args(argv)

    try:
        roots = resolve_roots(args.active_root, args.primary_root)
        notes_path = resolve_for_write(args.notes, roots.primary_repo_root, allow_docs=args.allow_docs)
        if is_codex_worktree(notes_path):
            raise ImplementationNotesError("refusing to append to a worktree-only notes path under ~/.codex/worktrees")
        if not notes_path.exists():
            raise ImplementationNotesError(f"notes file does not exist: {notes_path}")
        session_id = os.environ.get("CODEX_SESSION_ID") or os.environ.get("RALPH_SESSION_ID") or ""
        ensure_not_red("implementation note entry", "\n".join([args.decision, args.reason, args.impact, *args.related_file, args.status]))
        operation_id = args.operation_id or os.environ.get("RALPH_OPERATION_ID") or uuid.uuid4().hex
        entry = entry_html(
            category=args.category,
            decision=args.decision,
            reason=args.reason,
            impact=args.impact,
            related_files=args.related_file,
            status=args.status,
            timestamp=now_local(),
            operation_id=operation_id,
        )
        ensure_not_red("rendered implementation note entry", entry)
        append_note_and_refresh(
            primary_root=roots.primary_repo_root,
            notes_path=notes_path,
            entry_html_text=entry,
            category=args.category,
            active_root=roots.active_worktree_root,
            session_id=session_id,
            operation_id=operation_id,
        )
        print(f"IMPLEMENTATION_NOTE_APPENDED {notes_path}")
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_NOTES_ERROR {exc}", file=sys.stderr)
        return 1


def read_context(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Read bounded implementation context from canonical plan notes.")
    parser.add_argument("--compat-legacy", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--active-root", required=True)
    parser.add_argument("--primary-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--mode", choices=("session-start", "explicit"), default="session-start")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        roots = resolve_roots(args.active_root, args.primary_root)
        selection = select_implementation_context(
            active_root=roots.active_worktree_root,
            primary_root=roots.primary_repo_root,
            session_id=args.session_id,
            explicit_plan=Path(args.plan) if args.plan else None,
        )
        if selection is None:
            if args.format == "json":
                print(json.dumps({"selection": None, "text": ""}, sort_keys=True))
            return 0
        rendered = render_implementation_context(selection=selection)
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "selection": {
                            "plan_path": str(selection.plan_path),
                            "notes_path": str(selection.notes_path),
                            "selection_reason": selection.selection_reason,
                            "branch": selection.branch,
                            "workspace_instance_id": selection.workspace_instance_id,
                            "notes_content_hash": selection.notes_content_hash,
                        },
                        "text": rendered,
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
        elif rendered:
            print(rendered)
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_CONTEXT_ERROR {exc}", file=sys.stderr)
        return 1


def update_index(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Update the project implementation index.")
    parser.add_argument("--compat-legacy", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--active-root", help="Active worktree root override.")
    parser.add_argument("--primary-root", help="Canonical local repo root override.")
    parser.add_argument("--plan", help="Canonical plan path for a planned implementation entry.")
    parser.add_argument("--notes", help="Canonical implementation notes path for a planned implementation entry.")
    parser.add_argument("--status", default="implemented", help="Plan entry status.")
    parser.add_argument("--commit", help="Commit to associate with the plan entry.")
    parser.add_argument("--branch", default="", help="Branch name override.")
    parser.add_argument("--pr", default="", help="PR URL or identifier.")
    parser.add_argument("--session-id", default="", help="Codex session id.")
    parser.add_argument("--event", choices=sorted(ALLOWED_EVENTS), default="", help="Lifecycle event to record.")
    parser.add_argument("--loose-commit", help="Commit without an approved plan.")
    parser.add_argument("--reason", default="", help="Reason for a loose commit entry.")
    parser.add_argument("--entry-notes", default="", help="Short note for a loose commit entry.")
    args = parser.parse_args(argv)
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
            event=args.event,
        )
        print(f"IMPLEMENTATION_INDEX_PLAN {plan_path}")
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_INDEX_ERROR {exc}", file=sys.stderr)
        return 1
