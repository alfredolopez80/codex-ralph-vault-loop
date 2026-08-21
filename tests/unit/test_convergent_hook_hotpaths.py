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


def test_quoted_patterns_ranges_and_read_only_pipelines_are_fast_path() -> None:
    for command in (
        "rg 'allow|block' docs",
        "sed -n '1,80p' docs/codex-hooks.md",
        "nl -ba docs/codex-hooks.md | head -n 40",
        "rg -n hooks docs 2>&1 | head -c 6000",
    ):
        assert successful_read_fast_path(event(tool_input={"cmd": command})).eligible is True, command


def test_external_agent_and_test_reads_are_never_fast_path() -> None:
    assert successful_read_fast_path(event(tool_name="mcp__catalog.read")).eligible is False
    assert successful_read_fast_path(event(tool_name="Agent")).eligible is False
    assert successful_read_fast_path(event(tool_input={"cmd": "pytest tests/unit -q"})).eligible is False
    assert successful_read_fast_path(event(tool_name="web_search")).eligible is False
    assert successful_read_fast_path(event(tool_name="google_drive_search")).eligible is False


def test_truncated_output_is_not_materiality_safe() -> None:
    result = successful_read_fast_path(event(tool_response={"exit_code": 0, "stdout": "x" * 2_001 + " P0"}))
    assert result.reason == "materiality_unknown"


def test_fast_path_rejects_structured_or_contradictory_results() -> None:
    assert successful_read_fast_path(event(tool_response={"exit_code": 0, "content": [{"type": "text", "text": "P1 BLOCKER"}]})).eligible is False
    assert successful_read_fast_path(event(success=True, tool_response={"exit_code": 1, "stdout": "failed"})).eligible is False
    assert successful_read_fast_path(event(tool_input={"cmd": "cat " + ("x" * 4_100)})).eligible is False


def test_fast_path_rejects_attached_sed_programs_and_path_aliases() -> None:
    for command in (
        "sed --expression='w /tmp/out' input.txt",
        "sed -e'w /tmp/out' input.txt",
        "./cat file",
        "tools/sed -n 1p file",
        "/tmp/git status --short",
    ):
        assert successful_read_fast_path(event(tool_input={"cmd": command})).eligible is False, command


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
        "fd -xrm {}",
        "fd -Xrm {}",
        "fdfind -xrm {}",
        "fdfind -Xrm {}",
        "git branch -D victim",
        "git branch -m old new",
        "git branch new-branch",
        "git diff --output=/tmp/leak",
        "git diff -o/tmp/leak",
        "git log --output /tmp/leak",
        "git show -o /tmp/leak HEAD",
        "rg --pre 'touch /tmp/mutated' pattern .",
        "rg --pre=python pattern .",
        "git branch --set-upstream-to=origin/main",
        "git diff --ext-diff",
        "git show --textconv HEAD",
        "sed -n '/x/w /tmp/out' file",
        "less -o /tmp/out file",
        "sort -o/tmp/out input.txt",
        "sort --output=/tmp/out input.txt",
        "sed -f rules.sed input.txt",
        "sed --file=rules.sed input.txt",
        'cat "$(touch /tmp/mutated)"',
        "cat `touch /tmp/mutated`",
        "cat file>/tmp/out",
        "find . -fprint0 /tmp/out",
        "file --compile -m magic",
        'sed -n "1e touch /tmp/x" file',
        "cat file & touch /tmp/mutated",
        "cat $MUTATING_OPTION file",
        "file -C -m magic",
        "less -O /tmp/out file",
        "rg --hostname-bin=touch pattern .",
        "git remote show origin",
    ):
        result = successful_read_fast_path(event(tool_input={"cmd": command}))
        assert result.eligible is False, command


def test_fast_path_rejects_unscanned_structured_response_fields() -> None:
    for response in (
        {"exit_code": 0, "structuredContent": {"result": "P1 BLOCKER"}},
        {"exit_code": 0, "data": {"message": "ROUTE_DECISION required"}},
        {"exit_code": 0, "plugin_payload": object()},
    ):
        assert successful_read_fast_path(event(tool_response=response)).eligible is False
