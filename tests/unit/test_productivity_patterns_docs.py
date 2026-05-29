from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_productivity_patterns_keep_report_only_automation_contract() -> None:
    text = (ROOT / "docs" / "codex-productivity-patterns.md").read_text(encoding="utf-8")

    assert "Every Friday at 10:00 AM" in text
    assert "report-only AutoResearch validation" in text
    assert "Do not edit files" in text
    assert "change global AGENTS" in text
    assert "PYTHONDONTWRITEBYTECODE=1" in text
    assert text.count("git status --short") >= 2
    assert "Ask for explicit approval before any recommendation is added to the global" in text


def test_productivity_patterns_do_not_adopt_unsafe_continuity_or_permissions() -> None:
    text = (ROOT / "docs" / "codex-productivity-patterns.md").read_text(encoding="utf-8")

    assert "| `/resume` and `/compact` | Do not adopt as Ralph continuity |" in text
    assert "| `/permissions` | Do not adopt |" in text
    assert "| `--yolo` | Do not adopt |" in text
    assert "$handoff" in text
    assert "wakeup/recall" in text
    assert "implementation notes" in text
