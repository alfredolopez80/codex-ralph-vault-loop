from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "scripts" / "plans"
if str(PLANS) not in sys.path:
    sys.path.insert(0, str(PLANS))

from implementation_notes_consolidator import scan_notes_roots


def test_scan_notes_roots_preserves_nested_relative_keys_and_leaf_collisions(tmp_path: Path) -> None:
    primary = tmp_path / "repo"
    plans = primary / ".ralph" / "plans"
    for relative in ("nested/feature", "other/feature"):
        notes = plans / f"{relative}-implementation-notes.html"
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text("<main data-implementation-notes=\"true\"></main>\n", encoding="utf-8")

    records = scan_notes_roots(primary, primary, [])

    assert set(records) == {"nested/feature", "other/feature"}
    assert records["nested/feature"].primary_notes == plans / "nested/feature-implementation-notes.html"
    assert records["other/feature"].primary_notes == plans / "other/feature-implementation-notes.html"
