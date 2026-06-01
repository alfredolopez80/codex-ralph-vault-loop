from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from consolidated_notes_artifacts import ConsolidatedPlanSection, current_entries, legacy_excerpt
from implementation_index_lib import load_index, upsert_plan_entry, write_index
from implementation_notes_lib import (
    IMPLEMENTATION_NOTES_SUFFIX,
    ImplementationNotesError,
    ensure_not_red,
    parse_plan_metadata,
    resolve_for_write,
    run_git,
    valid_non_initial_entries,
)


LEGACY_ENTRY_RE = re.compile(r"<(?:article|section)\b", re.IGNORECASE)
UNSAFE_NOTES_HTML_RE = re.compile(
    r"(?is)"
    r"<\s*(script|iframe|object|embed|base|form|input|button|textarea|select|svg|math)\b"
    r"|<\s*link\b"
    r"|<[^>]+\s+on[a-z0-9_-]+\s*="
    r"|(?:href|src|xlink:href)\s*=\s*(['\"]?)\s*(?:javascript:|data:text/html|data:application)"
)
META_HTTP_EQUIV_RE = re.compile(r"(?is)<\s*meta\b[^>]*http-equiv\s*=\s*(?:['\"]([^'\"]+)['\"]|([^\s>]+))[^>]*>")


@dataclass
class NotesCopy:
    path: Path
    location: str
    sha256: str
    notes_root: Path
    repo_root: Path


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


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def validate_notes_source(path: Path, notes_root: Path, repo_root: Path) -> str:
    if any(part == ".." for part in path.expanduser().parts):
        return f"path traversal is not allowed: {path}"
    resolved_repo = repo_root.resolve(strict=False)
    resolved_root = notes_root.resolve(strict=False)
    if not _is_relative_to(resolved_root, resolved_repo):
        return f"implementation notes root escapes repo root: {notes_root}"
    resolved_path = path.resolve(strict=False)
    if path.is_symlink() and not _is_relative_to(resolved_path, resolved_root):
        return f"implementation notes symlink target escapes .ralph/plans: {path}"
    if not _is_relative_to(resolved_path, resolved_root):
        return f"implementation notes source escapes .ralph/plans: {path}"
    return ""


def slug_for_notes(path: Path) -> str:
    name = path.name
    if not name.endswith(IMPLEMENTATION_NOTES_SUFFIX):
        raise ImplementationNotesError(f"not an implementation notes file: {path}")
    return name[: -len(IMPLEMENTATION_NOTES_SUFFIX)]


def unsafe_notes_html_match(text: str) -> re.Match[str] | None:
    active_match = UNSAFE_NOTES_HTML_RE.search(text)
    if active_match:
        return active_match
    for meta_match in META_HTTP_EQUIV_RE.finditer(text):
        value = (meta_match.group(1) or meta_match.group(2) or "").strip().lower()
        if value != "content-security-policy":
            return meta_match
    return None


def classify_notes(path: Path) -> tuple[str, int, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    ensure_not_red(f"implementation notes file {path}", text)
    unsafe_match = unsafe_notes_html_match(text)
    if unsafe_match:
        legacy_count = len(LEGACY_ENTRY_RE.findall(text))
        matched = unsafe_match.group(0).strip().split()[0]
        return "invalid", legacy_count, f"unsafe implementation notes HTML is not allowed: {matched}"
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
            record = record_for(slug)
            source_error = validate_notes_source(path, root_plans, root)
            if source_error:
                record.conflicts.append(source_error)
                record.copies.append(NotesCopy(path=path, location=location, sha256="", notes_root=root_plans, repo_root=root))
                continue
            record.copies.append(NotesCopy(path=path, location=location, sha256=sha256(path), notes_root=root_plans, repo_root=root))
    return records


def analyze_record(record: NotesRecord, primary_root: Path, indexed_notes: set[str]) -> None:
    if record.conflicts:
        return
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

    if record.schema == "invalid":
        record.conflicts.append(f"implementation notes schema is invalid: {record.schema_error}")

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
        source_copy = next(copy for copy in record.copies if copy.path.resolve(strict=False) != record.primary_notes.resolve(strict=False))
        source_error = validate_notes_source(source_copy.path, source_copy.notes_root, source_copy.repo_root)
        if source_error:
            raise ImplementationNotesError(source_error)
        target = resolve_for_write(record.primary_notes, primary_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_copy.path, target)

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


def build_consolidated_sections(records: list[NotesRecord]) -> list[ConsolidatedPlanSection]:
    sections: list[ConsolidatedPlanSection] = []
    for record in records:
        if record.conflicts or record.schema not in {"current", "legacy"} or not record.primary_notes.exists():
            continue
        if record.schema == "current":
            entries = current_entries(record.primary_notes)
            excerpt = ""
        else:
            entries = []
            excerpt = legacy_excerpt(record.primary_notes)
        sections.append(
            ConsolidatedPlanSection(
                slug=record.slug,
                plan_path=record.plan_path,
                notes_path=record.primary_notes,
                schema=record.schema,
                status=plan_status(record.plan_path, record.schema),
                source_sha256=sha256(record.primary_notes),
                entries=entries,
                legacy_excerpt=excerpt,
            )
        )
    return sections
