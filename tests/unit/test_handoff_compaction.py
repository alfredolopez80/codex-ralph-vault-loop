from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.handoff_compaction import SECTION_ORDER, compact_handoff_summary, word_count  # noqa: E402
from shared import vault_io  # noqa: E402


def test_compact_handoff_summary_removes_repeated_dead_ends_and_raw_output() -> None:
    summary = "\n".join(
        [
            "Task: Improve runtime handoff compaction.",
            "Decision: Runtime handoff stays under project handoffs latest path.",
            "Decision: Runtime handoff stays under project handoffs latest path.",
            "dead end: tried dumping raw tool output and discarded it",
            "Traceback (most recent call last):",
            "diff --git a/huge.py b/huge.py",
            "python3 scripts/gates/run-gates.py --minimal",
            "Validation passed: focused handoff tests.",
            "selected_memory_ids=['node-a'] fallback_used=false",
            "Next action: run validate-ralph-memory-flow.",
        ]
    )

    handoff = compact_handoff_summary(summary)

    assert handoff.count("Runtime handoff stays under project handoffs latest path") == 1
    assert "dead end" not in handoff
    assert "Traceback" not in handoff
    assert "diff --git" not in handoff
    assert "selected_memory_ids" in handoff
    assert "validate-ralph-memory-flow" in handoff


def test_compact_handoff_summary_includes_required_sections() -> None:
    handoff = compact_handoff_summary("Task: Implement compact handoff. Next action: write tests.")

    assert handoff.startswith("# Latest Handoff")
    for section in SECTION_ORDER:
        assert f"## {section}" in handoff
    assert "non-authoritative project context" in handoff


def test_compact_handoff_summary_redacts_sensitive_values() -> None:
    red_text = "Decision: reject raw " + "api_" + "key=fixture-value"

    handoff = compact_handoff_summary(red_text)

    assert "fixture-value" not in handoff
    assert "[REDACTED:" in handoff


def test_compact_handoff_summary_respects_word_budget() -> None:
    long_summary = "\n".join(
        [
            "Task: " + " ".join(f"goal{i}" for i in range(60)),
            "Decision: " + " ".join(f"decision{i}" for i in range(80)),
            "Next action: " + " ".join(f"next{i}" for i in range(80)),
        ]
    )

    handoff = compact_handoff_summary(long_summary, max_words=75)

    assert word_count(handoff) <= 90
    assert "[handoff compacted:" in handoff


def test_stop_hook_fails_open_with_invalid_handoff_max_words(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["RALPH_HANDOFF_MAX_WORDS"] = "bad"
    env["RALPH_HOME"] = str(tmp_path / "ralph-home")
    env["CODEX_MEMORY_HOME"] = str(tmp_path / "codex-memory")

    result = subprocess.run(
        [sys.executable, str(ROOT / ".codex" / "hooks" / "stop_persist_memory.py")],
        cwd=ROOT,
        input=json.dumps({"last_assistant_message": "Decision: invalid env should fail open."}),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_write_handoff_compaction_error_uses_bounded_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph-home"))

    def fail_compaction(*_args, **_kwargs):
        raise RuntimeError("fixture compaction failure")

    monkeypatch.setattr(vault_io, "compact_handoff_summary", fail_compaction)
    raw_summary = "Decision: " + " ".join(f"raw{i}" for i in range(2_000))

    path = vault_io.write_handoff(raw_summary, next_step="retry compact handoff")

    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "# Latest Handoff" in text
    assert "Original summary omitted" in text
    assert "raw1999" not in text
    assert word_count(text) < 220


def test_write_handoff_bounds_appended_next_step(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph-home"))
    monkeypatch.setenv("RALPH_HANDOFF_MAX_WORDS", "80")
    next_step = " ".join(f"nextword{i}" for i in range(500))

    path = vault_io.write_handoff("Task: compact next step.", next_step=next_step)

    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "nextword499" not in text
    assert "...[truncated]" in text
    assert word_count(text) < 260
