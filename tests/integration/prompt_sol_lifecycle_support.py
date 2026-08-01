from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HOOK_CONFIG = ROOT / ".codex" / "hooks.json"
ROUTING_STATE_FILE = "sol-advisor.json"
ROUTING_STATE_KEY = "routing"
IMMUTABLE_SOURCES = (
    ROOT / ".codex" / "config.toml",
    HOOK_CONFIG,
    ROOT / ".codex" / "hooks" / "sol_advisor_prompt_state.py",
    ROOT / ".codex" / "hooks" / "subagent_routing_pretool_guard.py",
    ROOT / ".codex" / "hooks" / "sol_advisor_pretool_guard.py",
    ROOT / ".codex" / "hooks" / "sol_advisor_subagent_context.py",
    ROOT / ".codex" / "hooks" / "sol_advisor_subagent_stop.py",
    ROOT / ".codex" / "hooks" / "sol_advisor_stop_guard.py",
)


def isolated_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "CODEX_HOOK_STATE_ROOT": str(tmp_path / "hook-state"),
            "RALPH_HOME": str(tmp_path / "ralph-home"),
            "CODEX_MEMORY_HOME": str(tmp_path / "empty-memory"),
            "VAULT_DIR": str(tmp_path / "vault"),
            "VAULT_PROJECT": "lifecycle-e2e",
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_SLOP_GUARD_ENABLED": "0",
        }
    )
    return env


def immutable_source_snapshot() -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in IMMUTABLE_SOURCES}


def assert_sources_unchanged(snapshot: dict[Path, bytes]) -> None:
    assert {path: path.read_bytes() for path in snapshot} == snapshot


def configured_commands(event: str) -> list[str]:
    config = json.loads(HOOK_CONFIG.read_text(encoding="utf-8"))
    return [str(hook["command"]) for group in config["hooks"][event] for hook in group["hooks"]]


def configured_command(event: str, script_name: str) -> str:
    return next(command for command in configured_commands(event) if script_name in command)


def run_command(command: str, payload: dict[str, Any], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
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


def json_payloads(output: str) -> Iterable[dict[str, Any]]:
    try:
        whole_output = json.loads(output)
    except json.JSONDecodeError:
        whole_output = None
    if isinstance(whole_output, dict):
        yield whole_output
        return
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def blocking_payload(output: str) -> dict[str, Any] | None:
    return next((value for value in json_payloads(output) if value.get("decision") == "block"), None)


def run_configured_event(
    event: str,
    payload: dict[str, Any],
    env: dict[str, str],
    *,
    stop_on_block: bool = False,
) -> list[subprocess.CompletedProcess[str]]:
    results: list[subprocess.CompletedProcess[str]] = []
    for command in configured_commands(event):
        result = run_command(command, payload, env)
        assert result.returncode == 0, f"{event} {command}: {result.stderr or result.stdout}"
        results.append(result)
        if stop_on_block and blocking_payload(result.stdout):
            break
    return results


def prompt_payload(session_id: str, prompt: str) -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "session_id": session_id, "cwd": str(ROOT), "prompt": prompt}


def state_path(env: dict[str, str], session_id: str) -> Path:
    return Path(env["CODEX_HOOK_STATE_ROOT"]) / session_id / ROUTING_STATE_FILE


def routing_state(env: dict[str, str], session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = state_path(env, session_id)
    assert path.is_file(), f"missing lifecycle state: {path}"
    state = json.loads(path.read_text(encoding="utf-8"))
    decision = state.get(ROUTING_STATE_KEY)
    assert isinstance(decision, dict), f"missing bounded {ROUTING_STATE_KEY}: {state}"
    return state, decision


def assert_decision_fields(decision: dict[str, Any], **expected: object) -> None:
    for field, value in expected.items():
        assert decision.get(field) == value, f"{field}: expected {value!r}, got {decision.get(field)!r}"


def context_values(results: Iterable[subprocess.CompletedProcess[str]]) -> list[str]:
    contexts: list[str] = []
    for result in results:
        for value in json_payloads(result.stdout):
            hook_output = value.get("hookSpecificOutput")
            if isinstance(hook_output, dict) and isinstance(hook_output.get("additionalContext"), str):
                contexts.append(hook_output["additionalContext"])
    return contexts


def high_complexity_prompt() -> str:
    return (
        "Design an architecture migration for a system. Audit multiple validation steps and plan antes de modificar. "
        "Keep evidence bounded, locally verifiable, and focused on the intended transition. "
    ) * 3
