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


def test_global_dispatcher_routes_the_same_policy_in_a_neutral_workspace(tmp_path: Path) -> None:
    neutral = tmp_path / "neutral-workspace"
    neutral.mkdir()
    env = isolated_env(tmp_path)
    session_id = "global-sol-neutral-8"
    prompt = high_complexity_prompt()
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "cwd": str(neutral),
        "prompt": prompt,
    }

    outputs: list[str] = []
    for command in commands_for("UserPromptSubmit"):
        result = run(command, payload, env)
        assert result.returncode == 0, result.stderr or result.stdout
        outputs.append(result.stdout)

    state, decision = state_for(env, session_id)
    assert decision["policy_version"] == "subagent-routing-v2"
    assert decision["configured_executor_model"] == "gpt-5.6-luna"
    assert decision["configured_executor_effort"] == "max"
    assert decision["subagent_route"] == "sol-advisor"
    assert decision["subagent_effort"] == "high"
    assert prompt not in json.dumps(state)
    assert any("ROUTE_DECISION" in output and "subagent_route=sol-advisor" in output for output in outputs)
