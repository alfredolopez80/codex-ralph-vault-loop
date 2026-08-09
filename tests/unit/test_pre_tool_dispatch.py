from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "pre_tool_dispatch.py"
HOOKS = HOOK.parent
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import pre_tool_dispatch  # noqa: E402


def payload(tmp_path: Path, tool: str, tool_input: dict[str, object]) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "session_id": "pre-dispatch-test",
        "tool_name": tool,
        "tool_input": tool_input,
    }


def run_dispatch(tmp_path: Path, data: dict[str, object]) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "RALPH_HOME": str(tmp_path / "ralph"),
        "CODEX_HOOK_STATE_ROOT": str(tmp_path / "state"),
        "CODEX_MEMORY_HOME": str(tmp_path / "empty-memory"),
        "VAULT_DIR": str(tmp_path / "empty-vault"),
        "RALPH_LOCAL_NOTES_ROOTS": "",
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        input=json.dumps(data),
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
        env=env,
    )


def decision(result: subprocess.CompletedProcess[str]) -> dict[str, str] | None:
    assert result.returncode == 0, result.stderr
    if not result.stdout:
        return None
    value = json.loads(result.stdout)
    assert set(value) == {"decision", "reason"}
    return value


def test_safe_read_is_silent_and_destructive_command_is_blocked(tmp_path: Path) -> None:
    safe = run_dispatch(tmp_path, payload(tmp_path, "exec_command", {"cmd": "git status --short"}))
    assert decision(safe) is None
    command = "rm " + "-rf /"
    blocked = decision(run_dispatch(tmp_path, payload(tmp_path, "Bash", {"cmd": command})))
    assert blocked and blocked["decision"] == "block"


def test_remote_package_manager_requires_sfw_but_local_tests_are_allowed(tmp_path: Path) -> None:
    blocked = decision(run_dispatch(tmp_path, payload(tmp_path, "exec_command", {"cmd": "npm install fixture"})))
    assert blocked and "sfw" in blocked["reason"].lower()
    assert decision(run_dispatch(tmp_path, payload(tmp_path, "exec_command", {"cmd": "npm test"}))) is None


def test_write_aliases_reject_outside_and_symlink_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    for alias in ("apply_patch", "Edit", "Write"):
        data = payload(workspace, alias, {"path": str(outside / "changed.py")})
        blocked = decision(run_dispatch(tmp_path, data))
        assert blocked and "workspace" in blocked["reason"].lower()

    linked = workspace / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    blocked = decision(run_dispatch(tmp_path, payload(workspace, "Write", {"path": str(linked / "changed.py")})))
    assert blocked and "symbolic" in blocked["reason"].lower()


def test_external_payload_is_locally_classified_before_egress(tmp_path: Path) -> None:
    protected_name = "api_" + "key"
    protected_value = protected_name + "=fixture-value"
    blocked = decision(
        run_dispatch(tmp_path, payload(tmp_path, "mcp__remote__send", {"message": protected_value}))
    )
    assert blocked and "local" in blocked["reason"].lower()
    assert protected_value not in blocked["reason"]
    assert decision(run_dispatch(tmp_path, payload(tmp_path, "mcp__remote__read", {"query": "public docs"}))) is None


def test_spawn_route_is_checked_and_safety_deny_wins(tmp_path: Path) -> None:
    managed = payload(
        tmp_path,
        "spawn_agent",
        {"agent_type": "sol-advisor", "task_name": "sol_advisor", "model": "gpt-5.6-sol", "fork_turns": "none", "message": "bounded work"},
    )
    blocked = decision(run_dispatch(tmp_path, managed))
    assert blocked and "routing" in blocked["reason"].lower()

    destructive = dict(managed)
    destructive["tool_input"] = {**managed["tool_input"], "cmd": "git reset " + "--hard"}
    blocked = decision(run_dispatch(tmp_path, destructive))
    assert blocked and "destructive" in blocked["reason"].lower()


def test_identified_action_fails_closed_when_a_component_errors(monkeypatch, tmp_path: Path) -> None:
    def fail(_payload):
        raise RuntimeError("fixture guard failure")

    monkeypatch.setattr(pre_tool_dispatch, "_guard_main", fail)
    response, executed = pre_tool_dispatch.dispatch(payload(tmp_path, "exec_command", {"cmd": "git status"}))
    assert response and response["decision"] == "block"
    assert executed == ["safety"]


def test_invalid_json_is_fail_open_with_sanitized_stderr(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        input="[invalid",
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "RALPH_HOME": str(tmp_path / "ralph")},
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert "action unknown" in result.stderr
