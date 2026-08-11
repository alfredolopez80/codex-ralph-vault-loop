from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.convergent_hooks import successful_read_fast_path  # noqa: E402


def event(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "hook_event_name": "PostToolUse",
        "tool_name": "exec_command",
        "tool_input": {"cmd": "git status --short"},
        "tool_response": {"exit_code": 0, "stdout": "clean"},
        "success": True,
    }
    value.update(overrides)
    return value


def test_successful_read_is_eligible_and_material_signals_are_not() -> None:
    assert successful_read_fast_path(event()).eligible is True
    assert successful_read_fast_path(event(output="ROUTE_DECISION=approval")).reason == "material_signal"
    assert successful_read_fast_path(event(tool_response={"exit_code": 0, "session_id": 99})).reason == "partial_stream"
    assert successful_read_fast_path(event(tool_input={"cmd": "git status --short && touch file"})).reason == "write_signal"


def test_external_agent_and_test_reads_are_never_fast_path() -> None:
    assert successful_read_fast_path(event(tool_name="mcp__catalog.read")).eligible is False
    assert successful_read_fast_path(event(tool_name="Agent")).eligible is False
    assert successful_read_fast_path(event(tool_input={"cmd": "pytest tests/unit -q"})).eligible is False


def test_read_executables_with_write_options_are_never_fast_path() -> None:
    for command in (
        "sed -i 's/old/new/' file.txt",
        "find . -delete",
        "find . -exec rm {} ;",
        "rg --replace replacement pattern file.txt",
        "rg -r replacement pattern file.txt",
        "sed -n '1w output.txt' file.txt",
        "git remote add origin https://example.invalid/repo.git",
        "fd --exec rm {}",
        "fd --exec-batch rm {}",
    ):
        result = successful_read_fast_path(event(tool_input={"cmd": command}))
        assert result.eligible is False, command
