from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "scripts" / "plans"
if str(PLANS) not in sys.path:
    sys.path.insert(0, str(PLANS))

from implementation_notes_lib import CATEGORY_ORDER, Roots, html_document  # noqa: E402


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
