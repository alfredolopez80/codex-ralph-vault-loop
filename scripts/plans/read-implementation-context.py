#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from implementation_context import render_implementation_context, select_implementation_context
from implementation_notes_lib import ImplementationNotesError, resolve_roots


def payload(selection, rendered: str) -> dict[str, object]:
    return {
        "selection": {
            "plan_path": str(selection.plan_path),
            "notes_path": str(selection.notes_path),
            "selection_reason": selection.selection_reason,
            "branch": selection.branch,
            "workspace_instance_id": selection.workspace_instance_id,
            "notes_content_hash": selection.notes_content_hash,
        },
        "text": rendered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read bounded implementation context from canonical plan notes.")
    parser.add_argument("--active-root", required=True)
    parser.add_argument("--primary-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--mode", choices=("session-start", "explicit"), default="session-start")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
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
            print(json.dumps(payload(selection, rendered), ensure_ascii=True, sort_keys=True))
        elif rendered:
            print(rendered)
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_CONTEXT_ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
