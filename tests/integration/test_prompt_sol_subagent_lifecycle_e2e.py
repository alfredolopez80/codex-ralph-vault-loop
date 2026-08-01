from __future__ import annotations

import json
from pathlib import Path

from prompt_sol_lifecycle_support import (
    ROOT,
    assert_decision_fields,
    assert_sources_unchanged,
    blocking_payload,
    configured_command,
    context_values,
    high_complexity_prompt,
    immutable_source_snapshot,
    isolated_env,
    json_payloads,
    prompt_payload,
    run_command,
    run_configured_event,
    routing_state,
    seven_complexity_prompt,
    state_path,
)


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
        policy_version="subagent-routing-v2",
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


def test_configured_lifecycle_routes_complexity_seven_to_the_same_sol_advisor_lane(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    snapshot = immutable_source_snapshot()
    session_id = "sol-seventh-band"
    prompt = seven_complexity_prompt()

    results = run_configured_event("UserPromptSubmit", prompt_payload(session_id, prompt), env)
    classifier = next(json_payloads(results[0].stdout))
    assert "complexity=7/10" in classifier["hookSpecificOutput"]["additionalContext"]

    state, decision = routing_state(env, session_id)
    assert_decision_fields(
        decision,
        policy_version="subagent-routing-v2",
        raw_complexity=7,
        effective_complexity=7,
        subagent_route="sol-advisor",
        subagent_mode="advisor",
        subagent_model="gpt-5.6-sol",
        subagent_effort="high",
        spawn_required=True,
        reason_code="sol-advisor-7-8",
    )
    assert prompt not in json.dumps(state)
    assert any("subagent_route=sol-advisor" in context for context in context_values(results))

    spawn_arguments = dict(decision["spawn_arguments"])
    pretool_payload = {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "cwd": str(ROOT),
        "tool_name": "spawn_agent",
        "tool_input": {**spawn_arguments, "message": "Return a compact advisory verdict."},
    }
    pretool_results = run_configured_event("PreToolUse", pretool_payload, env)
    assert all(blocking_payload(result.stdout) is None for result in pretool_results)
    assert_sources_unchanged(snapshot)


def test_configured_routing_hook_covers_every_complexity_level(tmp_path: Path) -> None:
    snapshot = immutable_source_snapshot()
    hook = configured_command("UserPromptSubmit", "sol_advisor_prompt_state.py")
    expected_routes = {
        1: ("none", None, None),
        2: ("none", None, None),
        3: ("none", None, None),
        4: ("terra-implementation", "gpt-5.6-terra", "high"),
        5: ("terra-implementation", "gpt-5.6-terra", "high"),
        6: ("terra-implementation", "gpt-5.6-terra", "high"),
        7: ("sol-advisor", "gpt-5.6-sol", "high"),
        8: ("sol-advisor", "gpt-5.6-sol", "high"),
        9: ("sol-advisor", "gpt-5.6-sol", "xhigh"),
        10: ("sol-advisor", "gpt-5.6-sol", "max"),
    }

    for level, (expected_route, expected_model, expected_effort) in expected_routes.items():
        env = isolated_env(tmp_path / f"level-{level}")
        session_id = f"scale-{level}"
        intent = "implementation" if 4 <= level <= 6 else "architecture" if level >= 9 else "routine"
        payload = {
            **prompt_payload(session_id, f"Bounded scale verification for complexity {level}."),
            "complexity": level,
            "intent": intent,
        }

        results = run_configured_event("UserPromptSubmit", payload, env, commands=[hook])
        assert all(result.stdout for result in results)
        state, decision = routing_state(env, session_id)
        assert decision["policy_version"] == "subagent-routing-v2"
        assert decision["raw_complexity"] == level
        assert decision["effective_complexity"] == level
        assert decision["configured_executor_model"] == "gpt-5.6-luna"
        assert decision["configured_executor_effort"] == "max"
        assert decision["subagent_route"] == expected_route
        assert decision["subagent_model"] == expected_model
        assert decision["subagent_effort"] == expected_effort
        assert decision["spawn_required"] is (expected_route != "none")
        assert payload["prompt"] not in json.dumps(state)

    assert_sources_unchanged(snapshot)


def test_routing_guard_ignores_unrelated_tools_with_spawn_like_fields(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    guard = configured_command("PreToolUse", "subagent_routing_pretool_guard.py")
    result = run_command(
        guard,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "unrelated-tool-routing-fields",
            "cwd": str(ROOT),
            "tool_name": "exec_command",
            "tool_input": {
                "cmd": "echo route=sol-advisor",
                "model": "gpt-5.6-sol",
                "task_name": "sol_advisor",
                "route": "sol-advisor",
            },
        },
        env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


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


def test_configured_lifecycle_accepts_a_gated_active_sol_route(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    snapshot = immutable_source_snapshot()
    session_id = "sol-active-accepted-9"
    prompt_hook = configured_command("UserPromptSubmit", "sol_advisor_prompt_state.py")
    payload = {
        **prompt_payload(session_id, "Validate this bounded architecture decision."),
        "complexity": 9,
        "intent": "architecture",
        "active_analysis_enabled": True,
        "bounded_scope": True,
        "local_verification_available": True,
        "budget_class": "small",
        "task_subagent_override": {"route": "sol-active-analysis", "reasoning_effort": "xhigh"},
    }

    results = run_configured_event("UserPromptSubmit", payload, env, commands=[prompt_hook])
    assert all(result.stdout for result in results)
    state, decision = routing_state(env, session_id)
    assert decision["subagent_route"] == "sol-active-analysis"
    assert decision["subagent_mode"] == "active-analysis"
    assert decision["subagent_effort"] == "xhigh"
    spawn_arguments = dict(decision["spawn_arguments"])
    assert "subagent_route" not in spawn_arguments

    pretool_results = run_configured_event(
        "PreToolUse",
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "tool_input": {**spawn_arguments, "message": "Return a bounded active-analysis verdict."},
        },
        env,
        commands=[configured_command("PreToolUse", "subagent_routing_pretool_guard.py")],
    )
    assert all(blocking_payload(result.stdout) is None for result in pretool_results)
    assert state["routing"]["subagent_route"] == "sol-active-analysis"
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
