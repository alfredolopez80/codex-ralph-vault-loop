from __future__ import annotations

from pathlib import Path
from typing import Any

from consolidated_notes_artifacts import ConsolidatedPlanSection, append_consolidated_artifacts, planned_append_counts
from implementation_index_lib import load_index, write_index
from implementation_notes_lib import ImplementationNotesError, now_local


def append_and_index(primary_root: Path, html_path: Path, md_path: Path, sections: list[ConsolidatedPlanSection]) -> dict[str, int]:
    stats = append_consolidated_artifacts(primary_root, html_path, md_path, sections)
    write_consolidated_index_metadata(primary_root, html_path, md_path, sections, stats)
    return stats


def write_consolidated_index_metadata(
    primary_root: Path,
    html_path: Path,
    md_path: Path,
    sections: list[ConsolidatedPlanSection],
    stats: dict[str, int],
) -> None:
    entry_count = sum(len(section.entries) + (1 if section.legacy_excerpt else 0) for section in sections)
    if stats["items"] != entry_count:
        raise ImplementationNotesError("consolidated item count does not match source entry count")
    data = load_index(primary_root)
    data["consolidated_notes"] = {
        "html": html_path.resolve(strict=False).relative_to(primary_root.resolve(strict=False)).as_posix(),
        "markdown": md_path.resolve(strict=False).relative_to(primary_root.resolve(strict=False)).as_posix(),
        "plan_count": len(sections),
        "entry_count": entry_count,
        "last_html_append_count": stats["html_append"],
        "last_md_append_count": stats["md_append"],
        "updated_at": now_local(),
        "consolidated_by": "scripts/plans/consolidate-implementation-notes.py",
    }
    write_index(primary_root, data)


def render_report(
    *,
    records: list[Any],
    sections: list[ConsolidatedPlanSection],
    primary_root: Path,
    applied: bool,
    html_path: Path,
    md_path: Path,
    blocked: bool,
    append_stats: dict[str, int] | None = None,
) -> dict[str, object]:
    stats = append_stats or ({"items": 0, "html_append": 0, "md_append": 0} if blocked else planned_append_counts(sections, html_path, md_path))
    return {
        "applied": applied,
        "primary_repo_root": str(primary_root),
        "consolidated_artifacts": {
            "html": str(html_path),
            "markdown": str(md_path),
            "html_exists": html_path.exists(),
            "markdown_exists": md_path.exists(),
            "action": "blocked_by_conflicts" if blocked else ("append_complete" if applied else "append_on_apply"),
            "plan_count": len(sections),
            "entry_count": stats["items"],
            "html_append_count": stats["html_append"],
            "md_append_count": stats["md_append"],
        },
        "records": [record_payload(record) for record in records],
    }


def record_payload(record: Any) -> dict[str, object]:
    return {
        "slug": record.slug,
        "plan": str(record.plan_path),
        "notes": str(record.primary_notes),
        "schema": record.schema,
        "entry_count": record.entry_count,
        "indexed": record.indexed,
        "actions": record.actions,
        "conflicts": record.conflicts,
        "schema_error": record.schema_error,
        "copies": [{"path": str(copy.path), "location": copy.location, "sha256": copy.sha256} for copy in record.copies],
    }
