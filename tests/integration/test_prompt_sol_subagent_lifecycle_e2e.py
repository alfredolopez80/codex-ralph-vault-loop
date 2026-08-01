from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
HOOK_CONFIG = ROOT / ".codex" / "hooks.json"
ROUTING_STATE_FILE = "sol-advisor.json"
ROUTING_STATE_KEY = "routing"

# The lifecycle is allowed to write only to tmp_path.  These are the source
# surfaces that hooks must never change while classifying or guarding a route.
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
    commands: list[str] = []
    for group in config["hooks"][event]:
        for hook in group["hooks"]:
            commands.append(str(hook["command"]))
    return commands


def global_configured_commands(event: str) -> list[str]:
    config_path = Path.home() / ".codex" / "hooks.json"
    if not config_path.is_file():
        pytest.skip("global hooks are not installed in this environment")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    commands: list[str] = []
    for group in config["hooks"].get(event, []):
        for hook in group["hooks"]:
            commands.append(str(hook["command"]))
    return commands


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
    commands: list[str] | None = None,
) -> list[subprocess.CompletedProcess[str]]:
    results: list[subprocess.CompletedProcess[str]] = []
    for command in commands if commands is not None else configured_commands(event):
        result = run_command(command, payload, env)
        assert result.returncode == 0, f"{event} {command}: {result.stderr or result.stdout}"
        results.append(result)
        if stop_on_block and blocking_payload(result.stdout):
            break
    return results


def prompt_payload(session_id: str, prompt: str) -> dict[str, Any]:
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "cwd": str(ROOT),
        "prompt": prompt,
    }


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
            if not isinstance(hook_output, dict):
                continue
            context = hook_output.get("additionalContext")
            if isinstance(context, str):
                contexts.append(context)
    return contexts


def high_complexity_prompt() -> str:
    # The configured Aristotle classifier deterministically yields 8:
    # base 1 + length + multiple + architecture/migration + system + audit + plan.
    return (
        "Design an architecture migration for a system. Audit multiple validation steps and plan antes de modificar. "
        "Keep evidence bounded, locally verifiable, and focused on the intended transition. "
    ) * 3


def test_configured_lifecycle_routes_sol_advisor_and_releases_completion(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    snapshot = immutable_source_snapshot()
    session_id = "sol-positive-8"
    prompt = high_complexity_prompt()

    prompt_results = run_configured_event("UserPromptSubmit", prompt_payload(session_id, prompt), env)
    classifier = next(json_payloads(prompt_results[0].stdout))
    classifier_context = classifier["hookSpecificOutput"]["additionalContext"]
    assert "complexity=8/10" in classifier_context
    assert "route=DECOMPOSE_AND_VALIDATE" in classifier_context
    assert "Aristotle First Principles required" in classifier_context

    state, decision = routing_state(env, session_id)
    expected_spawn_arguments = {
        "agent_type": "sol-advisor",
        "fork_turns": "none",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "task_name": "sol_advisor",
    }
    assert_decision_fields(
        decision,
        policy_version="subagent-routing-v1",
        raw_complexity=8,
        effective_complexity=8,
        sensitivity="GREEN",
        configured_executor_model="gpt-5.6-luna",
        configured_executor_effort="max",
        subagent_route="sol-advisor",
        subagent_mode="advisor",
        subagent_model="gpt-5.6-sol",
        subagent_effort="high",
        spawn_required=True,
        spawn_arguments=expected_spawn_arguments,
    )
    assert prompt not in json.dumps(state)
    assert any(
        "ROUTE_DECISION" in context and "subagent_route=sol-advisor" in context
        for context in context_values(prompt_results)
    )

    spawn_arguments = dict(decision["spawn_arguments"])
    pretool_payload = {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "cwd": str(ROOT),
        "tool_name": "spawn_agent",
        "tool_input": {
            **spawn_arguments,
            "message": "Review the bounded decision and return a compact verdict.",
        },
    }
    pretool_results = run_configured_event("PreToolUse", pretool_payload, env)
    assert all(blocking_payload(result.stdout) is None for result in pretool_results)

    subagent_start = {
        "hook_event_name": "SubagentStart",
        "session_id": session_id,
        "cwd": str(ROOT),
        "agent_id": "sol-positive-agent",
        **spawn_arguments,
    }
    start_results = run_configured_event("SubagentStart", subagent_start, env)
    assert any("Advisor contract:" in context for context in context_values(start_results))
    started_state, started_decision = routing_state(env, session_id)
    assert started_decision == decision
    assert started_state["consultation_count"] == 1
    assert started_state["consulted_phases"]["plan"] == started_state["decision_fingerprint"]

    subagent_stop = {
        "hook_event_name": "SubagentStop",
        "session_id": session_id,
        "cwd": str(ROOT),
        "agent_id": "sol-positive-agent",
        "success": True,
        **spawn_arguments,
    }
    stop_results = run_configured_event("SubagentStop", subagent_stop, env)
    assert all(result.stdout == "" for result in stop_results)
    completed_state, completed_decision = routing_state(env, session_id)
    assert completed_decision == decision
    assert completed_state["advisor_completed"] is True
    assert completed_state["prior_verdict_fingerprint"] == completed_state["decision_fingerprint"]

    main_stop = {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "cwd": str(ROOT),
        "last_assistant_message": "ROUTE_DECISION\nsubagent_route=sol-advisor\nCompleted local lifecycle proof.",
    }
    final_guard = run_command(configured_command("Stop", "sol_advisor_stop_guard.py"), main_stop, env)
    assert final_guard.returncode == 0, final_guard.stderr
    assert blocking_payload(final_guard.stdout) is None
    assert_sources_unchanged(snapshot)


def test_configured_lifecycle_keeps_routine_work_local_without_sol(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    snapshot = immutable_source_snapshot()
    session_id = "sol-routine-1"
    prompt = "Explain the repository status in one paragraph."

    results = run_configured_event("UserPromptSubmit", prompt_payload(session_id, prompt), env)
    classifier = next(json_payloads(results[0].stdout))
    assert "complexity=1/10" in classifier["hookSpecificOutput"]["additionalContext"]
    assert "route=DIRECT" in classifier["hookSpecificOutput"]["additionalContext"]

    state, decision = routing_state(env, session_id)
    assert decision["subagent_route"] == "none"
    assert decision["subagent_mode"] == "none"
    assert decision["subagent_model"] is None
    assert decision["spawn_required"] is False
    assert state["consultation_count"] == 0
    assert not any("Sol advisor eligibility: yes" in context for context in context_values(results))
    assert_sources_unchanged(snapshot)


def test_configured_lifecycle_rejects_active_sol_below_effective_nine(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    snapshot = immutable_source_snapshot()
    session_id = "sol-active-rejected-8"
    prompt = high_complexity_prompt()

    run_configured_event("UserPromptSubmit", prompt_payload(session_id, prompt), env)
    state, decision = routing_state(env, session_id)
    assert decision["effective_complexity"] == 8
    assert decision["active_analysis_eligible"] is False
    assert decision["active_analysis_rejection_reason"] == "active-analysis-requires-effective-complexity-9"

    rejected_active_spawn = {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "cwd": str(ROOT),
        "tool_name": "spawn_agent",
        "tool_input": {
            "agent_type": "sol-advisor",
            "task_name": "sol_advisor",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "fork_turns": "none",
            "message": "Perform bounded active analysis.",
        },
    }
    results = run_configured_event("PreToolUse", rejected_active_spawn, env, stop_on_block=True)
    block = next((blocking_payload(result.stdout) for result in results if blocking_payload(result.stdout)), None)
    assert block is not None
    assert isinstance(block.get("reason"), str) and block["reason"].strip()

    rejected_state, rejected_decision = routing_state(env, session_id)
    assert rejected_decision == decision
    assert rejected_state["consultation_count"] == state["consultation_count"] == 0
    assert_sources_unchanged(snapshot)


def test_configured_lifecycle_blocks_red_before_route_or_subagent_creation(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    snapshot = immutable_source_snapshot()
    session_id = "sol-red-local-only"
    red_marker = "api" + "_key" + "=lifecycle-red-sentinel"
    prompt = f"Please route this {red_marker} through a deep architecture review."

    results = run_configured_event(
        "UserPromptSubmit",
        prompt_payload(session_id, prompt),
        env,
        stop_on_block=True,
    )
    block = next((blocking_payload(result.stdout) for result in results if blocking_payload(result.stdout)), None)
    assert block is not None
    assert "RED-sensitive" in str(block["reason"])
    assert not state_path(env, session_id).exists()
    assert not any("Sol advisor eligibility: yes" in context for context in context_values(results))

    generated = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert red_marker not in generated
    assert_sources_unchanged(snapshot)


def test_global_dispatcher_routes_the_same_policy_in_a_neutral_workspace(tmp_path: Path) -> None:
    neutral = tmp_path / "neutral-workspace"
    neutral.mkdir()
    env = isolated_env(tmp_path)
    session_id = "global-sol-neutral-8"
    prompt = high_complexity_prompt()

    results = run_configured_event(
        "UserPromptSubmit",
        {
            **prompt_payload(session_id, prompt),
            "cwd": str(neutral),
        },
        env,
        commands=global_configured_commands("UserPromptSubmit"),
    )
    state, decision = routing_state(env, session_id)
    assert decision["policy_version"] == "subagent-routing-v1"
    assert decision["configured_executor_model"] == "gpt-5.6-luna"
    assert decision["configured_executor_effort"] == "max"
    assert decision["subagent_route"] == "sol-advisor"
    assert decision["subagent_effort"] == "high"
    assert prompt not in json.dumps(state)
    assert any(
        "ROUTE_DECISION" in context and "subagent_route=sol-advisor" in context
        for context in context_values(results)
    )
