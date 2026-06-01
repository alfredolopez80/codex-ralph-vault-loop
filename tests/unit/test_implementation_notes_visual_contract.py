from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "scripts" / "plans"
if str(PLANS) not in sys.path:
    sys.path.insert(0, str(PLANS))

from consolidated_notes_artifacts import (  # noqa: E402
    ConsolidatedEntry,
    ConsolidatedPlanSection,
    append_consolidated_artifacts,
    resolve_consolidated_paths,
)
from implementation_notes_lib import CATEGORY_ORDER, ImplementationNotesError, Roots, html_document  # noqa: E402


def test_generated_notes_html_carries_static_visual_contract(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    active = tmp_path / "active"
    plan = primary / ".ralph" / "plans" / "visual-plan.md"
    notes = primary / ".ralph" / "plans" / "visual-plan-implementation-notes.html"
    roots = Roots(active_worktree_root=active, primary_repo_root=primary)

    html = html_document(
        title="Implementation Notes - Visual Plan",
        plan_path=plan,
        notes_path=notes,
        roots=roots,
        git_sha="abc123",
        git_branch="feature/visual",
        session_id="visual-session",
        timestamp="2026-06-01T00:00:00+00:00",
    )

    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html
    assert "style-src 'unsafe-inline'" in html
    assert "<script" not in html
    assert '<main class="page" data-implementation-notes="true">' in html
    assert '<dl class="meta-grid" aria-label="Implementation metadata">' in html
    assert ".meta-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));" in html
    assert "@media (max-width: 820px)" in html
    assert ".meta-grid { grid-template-columns: 1fr; }" in html
    assert "overflow-wrap: anywhere" in html
    assert ".entry-section:not(:has(.entry)) { display: none; }" in html

    for category in CATEGORY_ORDER:
        assert f'data-entry-section="{category}"' in html
        assert f"IMPLEMENTATION_NOTES_{category.replace('-', '_').upper()}_ANCHOR" in html


def test_consolidated_notes_html_carries_static_visual_contract(tmp_path: Path) -> None:
    section = ConsolidatedPlanSection(
        slug="visual-plan",
        plan_path=tmp_path / ".ralph" / "plans" / "visual-plan.md",
        notes_path=tmp_path / ".ralph" / "plans" / "visual-plan-implementation-notes.html",
        schema="current",
        status="implemented",
        source_sha256="abc123",
        entries=[
            ConsolidatedEntry(
                category="decision",
                timestamp="2026-06-01T00:00:00+00:00",
                decision="Keep one consolidated HTML without overwriting source notes. <img src=x onerror=alert(1)>",
                reason="Readers need a single durable view with `inline code` and [click](javascript:alert(1)) preserved as text.",
                impact="Per-plan notes remain source artifacts.",
                related_files="visual-plan.md",
                status="implemented",
            )
        ],
    )

    html_path = tmp_path / ".ralph" / "plans" / "implementation-notes-consolidated.html"
    md_path = tmp_path / ".ralph" / "plans" / "implementation-notes-consolidated.md"
    stats = append_consolidated_artifacts(tmp_path, html_path, md_path, [section])
    html = html_path.read_text(encoding="utf-8")
    markdown = md_path.read_text(encoding="utf-8")

    assert stats == {"items": 1, "html_append": 1, "md_append": 1}
    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html
    assert "style-src 'unsafe-inline'" in html
    assert "<script" not in html
    assert '<main class="page" data-consolidated-implementation-notes="true">' in html
    assert '<dl class="meta-grid" aria-label="Consolidation metadata">' in html
    assert "@media (max-width: 900px)" in html
    assert ".meta-grid { grid-template-columns: 1fr; }" in html
    assert "overflow-wrap: anywhere" in html
    assert "Keep one consolidated HTML without overwriting source notes." in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "visual-plan-implementation-notes.html" in html
    assert "Keep one consolidated HTML without overwriting source notes." in markdown
    assert "<img src=x onerror=alert(1)>" not in markdown
    assert "&lt;img src=x onerror=alert\\(1\\)&gt;" in markdown
    assert "\\`inline code\\`" in markdown
    assert "[click](javascript:alert(1))" not in markdown
    assert "\\[click\\]\\(javascript:alert\\(1\\)\\)" in markdown
    assert "<!-- consolidated-key:" in markdown


def test_consolidated_notes_paths_reject_unsafe_targets(tmp_path: Path) -> None:
    plans = tmp_path / ".ralph" / "plans"
    plans.mkdir(parents=True)

    with pytest.raises(ImplementationNotesError, match="path traversal"):
        resolve_consolidated_paths(tmp_path, "../implementation-notes-consolidated.html", None)

    with pytest.raises(ImplementationNotesError, match="sensitive filename"):
        resolve_consolidated_paths(tmp_path, ".env.html", None)

    outside = tmp_path / "outside.html"
    link = plans / "implementation-notes-consolidated.html"
    link.symlink_to(outside)
    with pytest.raises(ImplementationNotesError, match="symlink target escapes"):
        resolve_consolidated_paths(tmp_path, None, None)

    with pytest.raises(ImplementationNotesError, match="must be distinct"):
        resolve_consolidated_paths(tmp_path, "same-output.html", "same-output.html")


def test_consolidated_notes_paths_reject_symlinked_plans_root(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    external = tmp_path / "external-plans"
    (primary / ".ralph").mkdir(parents=True)
    external.mkdir()
    (primary / ".ralph" / "plans").symlink_to(external)

    with pytest.raises(ImplementationNotesError, match="resolves outside primary repo"):
        resolve_consolidated_paths(primary, None, None)


def test_consolidated_notes_validate_targets_before_partial_write(tmp_path: Path) -> None:
    section = ConsolidatedPlanSection(
        slug="atomic-plan",
        plan_path=tmp_path / ".ralph" / "plans" / "atomic-plan.md",
        notes_path=tmp_path / ".ralph" / "plans" / "atomic-plan-implementation-notes.html",
        schema="current",
        status="implemented",
        source_sha256="abc123",
        entries=[
            ConsolidatedEntry(
                category="decision",
                timestamp="2026-06-01T00:00:00+00:00",
                decision="Do not write one consolidated artifact if the sibling cannot accept appends.",
                reason="Apply must reject bad targets before partial mutation.",
                impact="Users do not get half-updated generated views.",
                related_files="atomic-plan.md",
                status="implemented",
            )
        ],
    )
    html_path = tmp_path / ".ralph" / "plans" / "implementation-notes-consolidated.html"
    md_path = tmp_path / ".ralph" / "plans" / "implementation-notes-consolidated.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text("# Corrupt consolidated Markdown\n", encoding="utf-8")

    with pytest.raises(ImplementationNotesError, match="Markdown append anchor not found"):
        append_consolidated_artifacts(tmp_path, html_path, md_path, [section])

    assert not html_path.exists()
