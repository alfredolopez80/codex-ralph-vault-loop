from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_native_apply_patch_command_field_is_workspace_scoped(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = "*** Begin Patch\n*** Update File: notes.md\n@@\n-old\n+new\n*** End Patch"
    assert decision(run_dispatch(tmp_path, payload(workspace, "apply_patch", {"command": inside}))) is None

    outside_path = tmp_path / "outside.md"
    outside = f"*** Begin Patch\n*** Update File: {outside_path}\n@@\n-old\n+new\n*** End Patch"
    blocked = decision(run_dispatch(tmp_path, payload(workspace, "apply_patch", {"command": outside})))
    assert blocked and "workspace" in blocked["reason"].lower()


def test_native_exec_output_ceiling_satisfies_context_budget(tmp_path: Path) -> None:
    command = "python3 scripts/context/repo_map.py --root ."
    unbounded = decision(run_dispatch(tmp_path, payload(tmp_path, "exec_command", {"cmd": command})))
    assert unbounded and "context budget" in unbounded["reason"].lower()
    bounded = payload(
        tmp_path,
        "exec_command",
        {"cmd": command, "max_output_tokens": 2_000},
    )
    assert decision(run_dispatch(tmp_path, bounded)) is None


def test_conflicting_native_output_ceilings_do_not_bypass_context_budget(tmp_path: Path) -> None:
    command = "python3 scripts/context/repo_map.py --root ."
    ceiling_field = "max_output_" + "tokens"
    conflicting = payload(tmp_path, "exec_command", {"cmd": command, ceiling_field: 2_000})
    conflicting[ceiling_field] = 3_000
    blocked = decision(run_dispatch(tmp_path, conflicting))
    assert blocked and "context budget" in blocked["reason"].lower()

    matching = payload(tmp_path, "exec_command", {"cmd": command, ceiling_field: 2_000})
    matching[ceiling_field] = 2_000
    assert decision(run_dispatch(tmp_path, matching)) is None


def test_external_payload_is_locally_classified_before_egress(tmp_path: Path) -> None:
    protected_name = "api_" + "key"
    protected_value = protected_name + "=fixture-value"
    blocked = decision(
        run_dispatch(tmp_path, payload(tmp_path, "mcp__remote__send", {"message": protected_value}))
    )
    assert blocked and "local" in blocked["reason"].lower()
    assert protected_value not in blocked["reason"]
    assert decision(run_dispatch(tmp_path, payload(tmp_path, "mcp__remote__read", {"query": "public docs"}))) is None


def test_current_spawn_passes_without_state_and_safety_deny_still_wins(tmp_path: Path) -> None:
    managed = payload(
        tmp_path,
        "spawn_agent",
        {
            "agent_type": "default",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "max",
            "fork_context": False,
            "message": "bounded work",
        },
    )
    assert decision(run_dispatch(tmp_path, managed)) is None

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


def test_enforce_phase_gate_classifies_shell_reads_validations_and_mutations(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pre_tool_dispatch, "configured_activation_mode", lambda **_kwargs: "enforce")
    phases = {"value": "verify"}
    monkeypatch.setattr(
        pre_tool_dispatch,
        "load_authoritative_state",
        lambda _payload: (object(), {"phase": phases["value"]}),
    )
    read = payload(tmp_path, "exec_command", {"cmd": "git status --short"})
    assert pre_tool_dispatch._convergent_phase_gate(read, "exec_command") is None
    validation = payload(tmp_path, "exec_command", {"cmd": "python3 -m pytest tests/unit -q"})
    assert pre_tool_dispatch._convergent_phase_gate(validation, "exec_command") is None
    chained = payload(tmp_path, "exec_command", {"cmd": "pytest -q && touch changed.txt"})
    blocked = pre_tool_dispatch._convergent_phase_gate(chained, "exec_command")
    assert blocked and blocked["decision"] == "block"
    mutation = payload(tmp_path, "exec_command", {"cmd": "touch changed.txt"})
    blocked = pre_tool_dispatch._convergent_phase_gate(mutation, "exec_command")
    assert blocked and blocked["decision"] == "block"
    phases["value"] = "implement"
    assert pre_tool_dispatch._convergent_phase_gate(mutation, "exec_command") is None


@pytest.mark.parametrize(
    "command",
    [
        "PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/unit -q",
        "pytest -q",
        "npm test",
        "pnpm run typecheck",
        "make test",
        "mypy .",
        "ruff check .",
        "ruff format --check .",
        "tsc --noEmit",
        "bash .codex/tests/run-hook-tests.sh",
        "python3 scripts/gates/run-gates.py --minimal",
    ],
)
def test_validation_command_allowlist_accepts_only_closed_read_or_gate_forms(command: str) -> None:
    assert pre_tool_dispatch._is_validation_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q && touch changed.txt",
        "make test deploy",
        "ruff check --fix .",
        "ruff format .",
        "tsc",
        "bash .codex/tests/run-hook-tests.sh --rewrite",
        "./pytest -q",
    ],
)
def test_validation_command_allowlist_rejects_mutating_or_ambiguous_forms(command: str) -> None:
    assert pre_tool_dispatch._is_validation_command(command) is False


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
