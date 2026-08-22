from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
GLOBAL_CONFIG = Path.home() / ".codex" / "hooks.json"


def isolated_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "CODEX_HOOK_STATE_ROOT": str(tmp_path / "hook-state"),
            "RALPH_HOME": str(tmp_path / "ralph-home"),
            "CODEX_MEMORY_HOME": str(tmp_path / "empty-memory"),
            "VAULT_DIR": str(tmp_path / "vault"),
            "VAULT_PROJECT": "global-routing-e2e",
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_SLOP_GUARD_ENABLED": "0",
        }
    )
    return env


def commands_for(event: str) -> list[str]:
    if not GLOBAL_CONFIG.is_file():
        pytest.skip("global hooks are not installed in this environment")
    config = json.loads(GLOBAL_CONFIG.read_text(encoding="utf-8"))
    return [str(hook["command"]) for group in config["hooks"].get(event, []) for hook in group["hooks"]]


def run(command: str, payload: dict[str, Any], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        shell=True,
        check=False,
        timeout=30,
    )


def high_complexity_prompt() -> str:
    return (
        "Design an architecture migration for a system. Audit multiple validation steps and plan antes de modificar. "
        "Keep evidence bounded, locally verifiable, and focused on the intended transition. "
    ) * 3


def state_for(env: dict[str, str], session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(env["CODEX_HOOK_STATE_ROOT"]) / session_id / "sol-advisor.json"
    assert path.is_file(), path
    state = json.loads(path.read_text(encoding="utf-8"))
    decision = state.get("routing")
    assert isinstance(decision, dict), state
    return state, decision


def test_global_security_only_profile_omits_prompt_routing(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    session_id = "global-sol-neutral-8"
    prompt_commands = commands_for("UserPromptSubmit")
    pretool_commands = commands_for("PreToolUse")

    assert prompt_commands == []
    assert len(pretool_commands) == 1
    assert "security_pre_tool_dispatch" in pretool_commands[0]
    state_path = Path(env["CODEX_HOOK_STATE_ROOT"]) / session_id / "sol-advisor.json"
    assert not state_path.exists()
