from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "scripts" / "plans"
if str(PLANS) not in sys.path:
    sys.path.insert(0, str(PLANS))

from implementation_context import (
    ImplementationContextSelection,
    notes_hash,
    render_implementation_context,
)
from implementation_notes_lib import Roots, append_entry, entry_html, html_document


def selection_fixture(tmp_path: Path) -> ImplementationContextSelection:
    plan = tmp_path / ".ralph" / "plans" / "bounded-context.md"
    notes = tmp_path / ".ralph" / "plans" / "bounded-context-implementation-notes.html"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "# Bounded Retrieval\n\nImplementation notes status: active\n\n## Purpose\nPreserve material implementation decisions for recovery.\n",
        encoding="utf-8",
    )
    roots = Roots(active_worktree_root=tmp_path, primary_repo_root=tmp_path)
    notes.write_text(
        html_document(
            title="Implementation Notes - Bounded Retrieval",
            plan_path=plan,
            notes_path=notes,
            roots=roots,
            git_sha="abc",
            git_branch="main",
            session_id="context-test",
            timestamp="2026-07-27T10:00:00+00:00",
        ),
        encoding="utf-8",
    )
    for category, status, timestamp in [
        ("decision", "active", "2026-07-27T10:01:00+00:00"),
        ("deviation", "active", "2026-07-27T10:02:00+00:00"),
        ("open-question", "active", "2026-07-27T10:03:00+00:00"),
        ("validation", "active", "2026-07-27T10:04:00+00:00"),
    ]:
        append_entry(
            notes,
            entry_html(
                category=category,
                decision=(f"{category} " + "detail " * 120).strip(),
                reason="Bounded context must retain material state.",
                impact="Recovery can continue without reopening the full HTML document.",
                related_files=["scripts/plans/read-implementation-context.py"],
                status=status,
                timestamp=timestamp,
            ),
            category,
        )
    return ImplementationContextSelection(
        plan_path=plan,
        notes_path=notes,
        selection_reason="explicit",
        branch="main",
        workspace_instance_id="fixture",
        notes_content_hash=notes_hash(notes),
    )


def test_render_implementation_context_preserves_required_sections_within_budget(tmp_path: Path) -> None:
    rendered = render_implementation_context(selection=selection_fixture(tmp_path))

    assert len(rendered) <= 2_000
    assert len(rendered.split()) <= 250
    assert len(rendered.encode("utf-8")) <= 2_000
    assert rendered.index("## Active Implementation Context") < rendered.index("### Decisions")
    assert rendered.index("### Decisions") < rendered.index("### Deviations")
    assert rendered.index("### Deviations") < rendered.index("### Open Questions")
    assert rendered.index("### Open Questions") < rendered.index("### Validation")
    assert "Source notes:" in rendered
    assert "Preserve material implementation decisions" in rendered


def test_render_implementation_context_reserves_structure_before_long_entry_details(tmp_path: Path) -> None:
    selection = selection_fixture(tmp_path)
    for index, category in enumerate(("decision", "decision", "deviation", "deviation", "open-question", "open-question", "validation")):
        append_entry(
            selection.notes_path,
            entry_html(
                category=category,
                decision=(f"{category} {index} " + "detail " * 180).strip(),
                reason="reason " * 120,
                impact="impact " * 100,
                related_files=["scripts/plans/read-implementation-context.py"],
                status="active",
                timestamp=f"2026-07-27T10:{10 + index:02d}:00+00:00",
            ),
            category,
        )

    rendered = render_implementation_context(selection=selection)

    assert len(rendered) <= 2_000
    assert len(rendered.split()) <= 250
    for heading in ("### Decisions", "### Deviations", "### Open Questions", "### Validation"):
        assert heading in rendered
    assert f"Source notes: {selection.notes_path}" in rendered
