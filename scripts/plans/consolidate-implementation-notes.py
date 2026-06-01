#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from implementation_index_lib import load_index, upsert_plan_entry, write_index
from implementation_notes_lib import (
    IMPLEMENTATION_NOTES_SUFFIX,
    ImplementationNotesError,
    ensure_not_red,
    parse_plan_metadata,
    resolve_for_write,
    resolve_roots,
    run_git,
    valid_non_initial_entries,
)


LEGACY_ENTRY_RE = re.compile(r"<(?:article|section)\b", re.IGNORECASE)


@dataclass
class NotesCopy:
    path: Path
    root: Path
    location: str
    sha256: str


@dataclass
class NotesRecord:
    slug: str
    primary_notes: Path
    plan_path: Path
    copies: list[NotesCopy] = field(default_factory=list)
    schema: str = "missing"
    entry_count: int = 0
    schema_error: str = ""
    indexed: bool = False
    actions: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_worktree_paths(root: Path) -> list[Path]:
    raw = run_git(root, "worktree", "list", "--porcelain")
    paths: list[Path] = []
    for line in raw.splitlines():
        if not line.startswith("worktree "):
            continue
        candidate = Path(line.removeprefix("worktree ")).expanduser()
        if candidate.exists():
            paths.append(candidate.resolve())
    return paths


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def slug_for_notes(path: Path) -> str:
    name = path.name
    if not name.endswith(IMPLEMENTATION_NOTES_SUFFIX):
        raise ImplementationNotesError(f"not an implementation notes file: {path}")
    return name[: -len(IMPLEMENTATION_NOTES_SUFFIX)]


def classify_notes(path: Path) -> tuple[str, int, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    ensure_not_red(f"implementation notes file {path}", text)
    try:
        entries = valid_non_initial_entries(text)
        return "current", len(entries), ""
    except ImplementationNotesError as exc:
        legacy_count = len(LEGACY_ENTRY_RE.findall(text))
        if "<html" in text.lower() and "implementation notes" in text.lower() and legacy_count:
            return "legacy", legacy_count, str(exc)
        return "invalid", legacy_count, str(exc)


def plan_status(plan_path: Path, schema: str) -> str:
    if not plan_path.exists():
        return "unlinked"
    metadata = parse_plan_metadata(plan_path)
    status = metadata.implementation_notes_status.strip()
    if status:
        return status
    if schema == "legacy":
        return "legacy_schema"
    return "consolidated"


def scan_notes_roots(primary_root: Path, active_root: Path, extra_roots: list[Path]) -> dict[str, NotesRecord]:
    plans_root = primary_root / ".ralph" / "plans"
    records: dict[str, NotesRecord] = {}

    def record_for(slug: str) -> NotesRecord:
        if slug not in records:
            records[slug] = NotesRecord(
                slug=slug,
                primary_notes=plans_root / f"{slug}{IMPLEMENTATION_NOTES_SUFFIX}",
                plan_path=plans_root / f"{slug}.md",
            )
        return records[slug]

    candidate_roots = unique_paths([primary_root, active_root, *git_worktree_paths(active_root), *extra_roots])
    for root in candidate_roots:
        root_plans = root / ".ralph" / "plans"
        if not root_plans.exists():
            continue
        location = "primary" if root.resolve(strict=False) == primary_root.resolve(strict=False) else "worktree"
        for path in sorted(root_plans.glob(f"*{IMPLEMENTATION_NOTES_SUFFIX}")):
            slug = slug_for_notes(path)
            record_for(slug).copies.append(NotesCopy(path=path, root=root, location=location, sha256=sha256(path)))
    return records


def analyze_record(record: NotesRecord, primary_root: Path, indexed_notes: set[str]) -> None:
    primary_copy = next((copy for copy in record.copies if copy.path.resolve(strict=False) == record.primary_notes.resolve(strict=False)), None)
    worktree_copies = [copy for copy in record.copies if copy is not primary_copy]

    if primary_copy is None and not worktree_copies:
        record.conflicts.append("notes file is missing")
        return

    if primary_copy is None:
        unique_hashes = {copy.sha256 for copy in worktree_copies}
        if len(unique_hashes) == 1 and len(worktree_copies) == 1:
            record.actions.append("copy_worktree_notes_to_primary")
            source = worktree_copies[0].path
            record.schema, record.entry_count, record.schema_error = classify_notes(source)
        elif len(unique_hashes) == 1:
            record.actions.append("copy_one_of_identical_worktree_notes_to_primary")
            source = worktree_copies[0].path
            record.schema, record.entry_count, record.schema_error = classify_notes(source)
        else:
            record.conflicts.append("multiple worktree notes differ and no primary copy exists")
            source = worktree_copies[0].path
            record.schema, record.entry_count, record.schema_error = classify_notes(source)
    else:
        record.schema, record.entry_count, record.schema_error = classify_notes(primary_copy.path)
        for copy in worktree_copies:
            if copy.sha256 != primary_copy.sha256:
                record.conflicts.append(f"worktree copy differs from primary: {copy.path}")

    if not record.plan_path.exists():
        record.conflicts.append("matching plan file is missing in primary .ralph/plans")
        return

    notes_rel = record.primary_notes.resolve(strict=False).relative_to(primary_root.resolve(strict=False)).as_posix()
    record.indexed = notes_rel in indexed_notes
    if not record.indexed and record.schema in {"current", "legacy"} and not record.conflicts:
        record.actions.append("upsert_implementation_index")


def apply_record(record: NotesRecord, primary_root: Path, active_root: Path) -> None:
    if record.conflicts:
        return
    if any(action.startswith("copy_") for action in record.actions):
        source = next(copy.path for copy in record.copies if copy.path.resolve(strict=False) != record.primary_notes.resolve(strict=False))
        target = resolve_for_write(record.primary_notes, primary_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    if "upsert_implementation_index" not in record.actions:
        return

    entry = upsert_plan_entry(
        primary_root=primary_root,
        plan_path=record.plan_path,
        notes_path=record.primary_notes,
        status=plan_status(record.plan_path, record.schema),
        active_root=active_root,
    )
    entry["notes_schema"] = record.schema
    entry["notes_entry_count"] = record.entry_count
    entry["consolidated_by"] = "scripts/plans/consolidate-implementation-notes.py"
    data = load_index(primary_root)
    for item in data.get("plans", []):
        if isinstance(item, dict) and item.get("plan") == entry.get("plan"):
            item.update(
                {
                    "notes_schema": record.schema,
                    "notes_entry_count": record.entry_count,
                    "consolidated_by": "scripts/plans/consolidate-implementation-notes.py",
                }
            )
    write_index(primary_root, data)


def render_report(records: list[NotesRecord], primary_root: Path, applied: bool) -> dict[str, Any]:
    return {
        "applied": applied,
        "primary_repo_root": str(primary_root),
        "records": [
            {
                "slug": record.slug,
                "plan": str(record.plan_path),
                "notes": str(record.primary_notes),
                "schema": record.schema,
                "entry_count": record.entry_count,
                "indexed": record.indexed,
                "actions": record.actions,
                "conflicts": record.conflicts,
                "schema_error": record.schema_error,
                "copies": [
                    {
                        "path": str(copy.path),
                        "location": copy.location,
                        "sha256": copy.sha256,
                    }
                    for copy in record.copies
                ],
            }
            for record in records
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and consolidate implementation notes into primary .ralph/plans.")
    parser.add_argument("--active-root", help="Active worktree root override.")
    parser.add_argument("--primary-root", help="Canonical local repo root override.")
    parser.add_argument("--extra-root", action="append", default=[], help="Additional repo/worktree root to scan.")
    parser.add_argument("--apply", action="store_true", help="Apply safe copy/index updates. Default is dry-run inventory.")
    args = parser.parse_args()

    try:
        roots = resolve_roots(args.active_root, args.primary_root)
        extra_roots = [Path(value).expanduser().resolve() for value in args.extra_root]
        records_by_slug = scan_notes_roots(roots.primary_repo_root, roots.active_worktree_root, extra_roots)
        index = load_index(roots.primary_repo_root)
        indexed_notes = {str(item.get("notes")) for item in index.get("plans", []) if isinstance(item, dict)}
        records = [records_by_slug[key] for key in sorted(records_by_slug)]
        for record in records:
            analyze_record(record, roots.primary_repo_root, indexed_notes)

        if args.apply:
            blocked = [record for record in records if record.conflicts]
            if blocked:
                print(json.dumps(render_report(records, roots.primary_repo_root, applied=False), indent=2, sort_keys=True))
                print("IMPLEMENTATION_NOTES_CONSOLIDATE_ERROR conflicts must be resolved before --apply", file=sys.stderr)
                return 1
            for record in records:
                apply_record(record, roots.primary_repo_root, roots.active_worktree_root)
            records_by_slug = scan_notes_roots(roots.primary_repo_root, roots.active_worktree_root, extra_roots)
            index = load_index(roots.primary_repo_root)
            indexed_notes = {str(item.get("notes")) for item in index.get("plans", []) if isinstance(item, dict)}
            records = [records_by_slug[key] for key in sorted(records_by_slug)]
            for record in records:
                analyze_record(record, roots.primary_repo_root, indexed_notes)
            report = render_report(records, roots.primary_repo_root, applied=True)
        else:
            report = render_report(records, roots.primary_repo_root, applied=False)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except ImplementationNotesError as exc:
        print(f"IMPLEMENTATION_NOTES_CONSOLIDATE_ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
