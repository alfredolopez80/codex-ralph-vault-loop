#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from consolidated_notes_artifacts import (
    CONSOLIDATED_HTML_NAME,
    CONSOLIDATED_MD_NAME,
    resolve_consolidated_paths,
    validate_consolidated_targets,
)
from consolidation_report import append_and_index, render_report
from implementation_index_lib import (
    CorruptImplementationIndexError,
    FutureImplementationIndexError,
    empty_index,
    load_index,
)
from implementation_notes_consolidator import (
    analyze_record,
    apply_record,
    build_consolidated_sections,
    scan_notes_roots,
)
from implementation_notes_lib import ImplementationNotesError, resolve_roots


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and consolidate implementation notes into primary .ralph/plans.")
    parser.add_argument("--active-root", help="Active worktree root override.")
    parser.add_argument("--primary-root", help="Canonical local repo root override.")
    parser.add_argument("--extra-root", action="append", default=[], help="Additional repo/worktree root to scan.")
    parser.add_argument("--consolidated-html", help=f"Aggregate HTML path inside .ralph/plans. Defaults to {CONSOLIDATED_HTML_NAME}.")
    parser.add_argument("--consolidated-md", help=f"Aggregate Markdown path inside .ralph/plans. Defaults to {CONSOLIDATED_MD_NAME}.")
    parser.add_argument("--apply", action="store_true", help="Apply safe copy/index updates. Default is dry-run inventory.")
    parser.add_argument("--rebuild", action="store_true", help="With --apply, rewrite consolidated artifacts from current source notes instead of appending.")
    args = parser.parse_args()

    try:
        roots = resolve_roots(args.active_root, args.primary_root)
        extra_roots = [Path(value).expanduser().resolve() for value in args.extra_root]
        html_path, md_path = resolve_consolidated_paths(roots.primary_repo_root, args.consolidated_html, args.consolidated_md)
        records_by_slug = scan_notes_roots(roots.primary_repo_root, roots.active_worktree_root, extra_roots)
        index_health = {"status": "ok"}
        index_error: ImplementationNotesError | None = None
        try:
            index = load_index(roots.primary_repo_root, quarantine_corrupt=args.apply)
        except (CorruptImplementationIndexError, FutureImplementationIndexError) as exc:
            # Report-only mode must preserve the source and tell the caller
            # why the projected index state cannot be trusted. Apply mode can
            # still surface a future schema as a hard stop; corrupt indexes
            # are quarantined by the mutating loader before this branch.
            index = empty_index(roots.primary_repo_root)
            index_error = exc
            index_health = {
                "status": "future" if isinstance(exc, FutureImplementationIndexError) else "corrupt",
                "error": str(exc),
            }
        indexed_notes = {str(item.get("notes")) for item in index.get("plans", []) if isinstance(item, dict)}
        records = [records_by_slug[key] for key in sorted(records_by_slug)]
        for record in records:
            analyze_record(record, roots.primary_repo_root, indexed_notes)
        blocked = [record for record in records if record.conflicts]
        sections = build_consolidated_sections(records) if not blocked else []

        if index_error:
            report = render_report(
                records=records,
                sections=sections,
                primary_root=roots.primary_repo_root,
                applied=False,
                html_path=html_path,
                md_path=md_path,
                blocked=True,
                rebuild=args.rebuild,
                index_health=index_health,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            print(f"IMPLEMENTATION_NOTES_CONSOLIDATE_ERROR {index_error}", file=sys.stderr)
            return 1

        if args.apply:
            if blocked:
                report = render_report(records=records, sections=sections, primary_root=roots.primary_repo_root, applied=False, html_path=html_path, md_path=md_path, blocked=True, rebuild=args.rebuild, index_health=index_health)
                print(json.dumps(report, indent=2, sort_keys=True))
                print("IMPLEMENTATION_NOTES_CONSOLIDATE_ERROR conflicts must be resolved before --apply", file=sys.stderr)
                return 1
            validate_consolidated_targets(html_path, md_path)
            for record in records:
                apply_record(record, roots.primary_repo_root, roots.active_worktree_root)
            records_by_slug = scan_notes_roots(roots.primary_repo_root, roots.active_worktree_root, extra_roots)
            index = load_index(roots.primary_repo_root, quarantine_corrupt=True)
            indexed_notes = {str(item.get("notes")) for item in index.get("plans", []) if isinstance(item, dict)}
            records = [records_by_slug[key] for key in sorted(records_by_slug)]
            for record in records:
                analyze_record(record, roots.primary_repo_root, indexed_notes)
            blocked = [record for record in records if record.conflicts]
            sections = build_consolidated_sections(records) if not blocked else []
            if blocked:
                report = render_report(records=records, sections=sections, primary_root=roots.primary_repo_root, applied=False, html_path=html_path, md_path=md_path, blocked=True, rebuild=args.rebuild, index_health=index_health)
                print(json.dumps(report, indent=2, sort_keys=True))
                print("IMPLEMENTATION_NOTES_CONSOLIDATE_ERROR conflicts appeared after apply", file=sys.stderr)
                return 1
            append_stats = append_and_index(roots.primary_repo_root, html_path, md_path, sections, rebuild=args.rebuild)
            report = render_report(records=records, sections=sections, primary_root=roots.primary_repo_root, applied=True, html_path=html_path, md_path=md_path, blocked=False, append_stats=append_stats, rebuild=args.rebuild, index_health=index_health)
        else:
            report = render_report(records=records, sections=sections, primary_root=roots.primary_repo_root, applied=False, html_path=html_path, md_path=md_path, blocked=bool(blocked), rebuild=args.rebuild, index_health=index_health)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_NOTES_CONSOLIDATE_ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
