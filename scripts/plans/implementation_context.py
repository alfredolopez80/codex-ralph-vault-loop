from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from implementation_index_lib import current_git_metadata, load_index
from implementation_notes_lib import (
    ImplementationNotesError,
    ParsedEntry,
    canonical_plan_path,
    ensure_plan_path_allowed,
    parse_plan_metadata,
    read_implementation_plan_state,
    resolve_for_read,
    resolve_notes_path_for_plan,
    valid_non_initial_entries,
)

MAX_CONTEXT_CHARS = 2_000
MAX_CONTEXT_WORDS = 250
MAX_CONTEXT_UNITS = 500
RESOLVED_STATUSES = {"resolved", "closed", "complete"}


@dataclass(frozen=True)
class ImplementationContextSelection:
    plan_path: Path
    notes_path: Path
    selection_reason: str
    branch: str
    workspace_instance_id: str
    notes_content_hash: str


def workspace_instance_id(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def notes_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_implementation_context(
    *,
    active_root: Path,
    primary_root: Path,
    session_id: str,
    explicit_plan: Path | None,
) -> ImplementationContextSelection | None:
    active = active_root.resolve()
    primary = primary_root.resolve()
    branch = current_git_metadata(active)["branch"]
    instance_id = workspace_instance_id(active)
    if explicit_plan is not None:
        return selection_for_plan(explicit_plan, active, primary, "explicit", branch, instance_id)

    state = read_implementation_plan_state(active, session_id)
    if state and paths_match_state(state, active, primary):
        selected = selection_for_plan(Path(state.get("plan_path", "")), active, primary, "session_state", branch, instance_id)
        if selected is not None:
            return selected

    try:
        index = load_index(primary)
    except ImplementationNotesError:
        return None
    candidates: list[Path] = []
    for entry in index.get("plans", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "active" or entry.get("branch") != branch:
            continue
        if entry.get("workspace_instance_id") != instance_id:
            continue
        plan = primary / str(entry.get("plan", ""))
        if plan.is_file():
            candidates.append(plan)
    if len(candidates) != 1:
        return None
    return selection_for_plan(candidates[0], active, primary, "active_index", branch, instance_id)


def paths_match_state(state: dict[str, str], active: Path, primary: Path) -> bool:
    return (
        Path(state.get("active_worktree_root", ".")).resolve() == active
        and Path(state.get("primary_repo_root", ".")).resolve() == primary
    )


def selection_for_plan(
    plan: Path,
    active: Path,
    primary: Path,
    reason: str,
    branch: str,
    instance_id: str,
) -> ImplementationContextSelection | None:
    try:
        plan_path = resolve_for_read(plan)
        from implementation_notes_lib import Roots

        roots = Roots(active_worktree_root=active, primary_repo_root=primary)
        ensure_plan_path_allowed(plan_path, roots)
        canonical = canonical_plan_path(plan_path, primary)
        plan_path = canonical if canonical.is_file() else plan_path
        metadata = parse_plan_metadata(plan_path)
        notes_path = resolve_notes_path_for_plan(metadata, plan_path, primary)
        notes_path = resolve_for_read(notes_path)
        valid_non_initial_entries(notes_path.read_text(encoding="utf-8"))
    except (ImplementationNotesError, OSError, ValueError):
        return None
    return ImplementationContextSelection(
        plan_path=plan_path,
        notes_path=notes_path,
        selection_reason=reason,
        branch=branch,
        workspace_instance_id=instance_id,
        notes_content_hash=notes_hash(notes_path),
    )


def render_implementation_context(
    *,
    selection: ImplementationContextSelection,
    max_chars: int = MAX_CONTEXT_CHARS,
    max_words: int = MAX_CONTEXT_WORDS,
    max_context_units: int = MAX_CONTEXT_UNITS,
) -> str:
    text = selection.notes_path.read_text(encoding="utf-8")
    entries = valid_non_initial_entries(text)
    status, objective = plan_identity(selection.plan_path)
    header = [
        "## Active Implementation Context",
        f"Plan: {plan_title(selection.plan_path)}",
        f"Status: {status or 'active'}",
        f"Objective: {objective}",
    ]
    sections = [
        ("### Decisions", entries_for(entries, "decision", 3), True),
        ("### Deviations", entries_for(entries, "deviation", 2, unresolved=True), False),
        ("### Open Questions", entries_for(entries, "open-question", 3, unresolved=True), False),
        ("### Validation", entries_for(entries, "validation", 2), False),
    ]
    selected_lines: list[list[str]] = [[] for _heading, _entries, _reason in sections]
    source = f"Source notes: {selection.notes_path}"

    for section_index, (_heading, section_entries, include_reason) in enumerate(sections):
        for entry in section_entries:
            full = entry_line(entry, include_reason=include_reason)
            compact = entry_line(entry, include_reason=False)
            for candidate in (full, compact, compact_entry_line(entry)):
                proposed = [*selected_lines[section_index], candidate]
                trial = [*selected_lines]
                trial[section_index] = proposed
                if within_budget(render_context_lines(header, sections, trial, source), max_chars, max_words, max_context_units):
                    selected_lines[section_index] = proposed
                    break

    return render_context_lines(header, sections, selected_lines, source)


def selected_entry_hashes(selection: ImplementationContextSelection) -> list[str]:
    entries = valid_non_initial_entries(selection.notes_path.read_text(encoding="utf-8"))
    selected = (
        entries_for(entries, "decision", 3)
        + entries_for(entries, "deviation", 2, unresolved=True)
        + entries_for(entries, "open-question", 3, unresolved=True)
        + entries_for(entries, "validation", 2)
    )
    return [
        hashlib.sha256(
            "\n".join(
                (entry.category, entry.fields.get("Timestamp", ""), entry.fields.get("Decision", ""), entry.fields.get("Status", ""))
            ).encode("utf-8")
        ).hexdigest()
        for entry in selected
    ]


def plan_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def plan_identity(path: Path) -> tuple[str, str]:
    status = ""
    objective = ""
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.lower().startswith("implementation notes status:"):
            status = line.split(":", 1)[1].strip()
        if line.strip().lower() in {"## purpose", "## objective"}:
            for candidate in lines[index + 1 :]:
                if candidate.strip() and not candidate.startswith("#"):
                    objective = candidate.strip()
                    break
    if not objective:
        objective = plan_title(path)
    return status, compact_field(objective, 280)


def entries_for(entries: list[ParsedEntry], category: str, limit: int, unresolved: bool = False) -> list[ParsedEntry]:
    selected = [entry for entry in entries if entry.category == category]
    if unresolved:
        selected = [entry for entry in selected if entry.fields.get("Status", "").lower() not in RESOLVED_STATUSES]
    return sorted(selected, key=entry_order, reverse=True)[:limit]


def entry_order(entry: ParsedEntry) -> tuple[datetime, str]:
    value = entry.fields.get("Timestamp", "")
    try:
        return datetime.fromisoformat(value), value
    except ValueError:
        return datetime.min.replace(tzinfo=datetime.UTC), value


def entry_line(entry: ParsedEntry, *, include_reason: bool) -> str:
    decision = compact_field(entry.fields.get("Decision", ""), 220)
    impact = compact_field(entry.fields.get("Impact", ""), 160)
    detail = f"- {decision}"
    if include_reason:
        detail += f"; reason: {compact_field(entry.fields.get('Reason', ''), 170)}"
    if impact:
        detail += f"; impact: {impact}"
    return detail


def compact_entry_line(entry: ParsedEntry) -> str:
    return f"- {compact_field(entry.fields.get('Decision', ''), 96)}"


def render_context_lines(
    header: list[str],
    sections: list[tuple[str, list[ParsedEntry], bool]],
    selected_lines: list[list[str]],
    source: str,
) -> str:
    lines = [*header]
    for (heading, entries, _include_reason), section_lines in zip(sections, selected_lines, strict=True):
        lines.append(heading)
        lines.extend(section_lines or (["- None recorded."] if not entries else []))
    lines.append(source)
    return "\n".join(lines)


def compact_field(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


def within_budget(text: str, max_chars: int, max_words: int, max_units: int) -> bool:
    return (
        len(text) <= min(max_chars, max_units * 4)
        and len(text.split()) <= max_words
    )
