from __future__ import annotations

import json
import subprocess
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

    substituted_profile = {
        **pretool_payload,
        "tool_input": {**pretool_payload["tool_input"], "agent_type": "ralph-coder"},
    }
    substituted_results = run_configured_event(
        "PreToolUse", substituted_profile, env, stop_on_block=True
    )
    substituted_block = next(
        (blocking_payload(result.stdout) for result in substituted_results if blocking_payload(result.stdout)),
        None,
    )
    assert substituted_block is not None
    assert "agent_type" in str(substituted_block["reason"])

    subagent_start = {
        "hook_event_name": "SubagentStart",
        "session_id": session_id,
        "cwd": str(ROOT),
        "agent_id": "sol-positive-agent",
        "phase": "final",
        **spawn_arguments,
    }
    start_results = run_configured_event("SubagentStart", subagent_start, env)
    assert any("Advisor contract:" in context for context in context_values(start_results))
    started_state, started_decision = routing_state(env, session_id)
    assert started_decision == decision
    assert started_state["consultation_count"] == 1
    assert started_state["phase"] == "plan"
    assert started_state["consulted_phases"]["plan"] == started_state["decision_fingerprint"]

    duplicate_spawn = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "tool_input": {
                **spawn_arguments,
                "phase": "retry-2",
                "message": "Do not start a second plan consultation.",
            },
        },
        env,
    )
    duplicate_block = blocking_payload(duplicate_spawn.stdout)
    assert duplicate_block is not None
    assert "already been started" in str(duplicate_block["reason"])

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

    phase_shift = run_configured_event(
        "SubagentStart",
        {**subagent_start, "phase": "final", "agent_id": "equivalent-phase-start"},
        env,
    )
    assert all(blocking_payload(result.stdout) is None for result in phase_shift)
    phase_state, _ = routing_state(env, session_id)
    assert phase_state["phase"] == "final", phase_state
    equivalent_results = run_configured_event("PreToolUse", pretool_payload, env, stop_on_block=True)
    equivalent_block = next(
        (blocking_payload(result.stdout) for result in equivalent_results if blocking_payload(result.stdout)),
        None,
    )
    assert equivalent_block is not None
    assert "equivalent Sol verdict" in str(equivalent_block["reason"])

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


def test_routing_guard_validates_namespaced_spawn_agent_tools(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    session_id = "namespaced-spawn-agent"
    run_configured_event(
        "UserPromptSubmit",
        prompt_payload(session_id, high_complexity_prompt()),
        env,
    )
    _, decision = routing_state(env, session_id)
    result = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "collaboration.spawn_agent",
            "tool_input": {
                **dict(decision["spawn_arguments"]),
                "message": "Review this bounded decision and return a compact verdict.",
            },
        },
        env,
    )

    assert result.returncode == 0, result.stderr
    assert blocking_payload(result.stdout) is None


def test_routing_guard_blocks_conflicting_spawn_envelope_fields(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    session_id = "conflicting-spawn-envelope"
    run_configured_event("UserPromptSubmit", prompt_payload(session_id, high_complexity_prompt()), env)
    _, decision = routing_state(env, session_id)
    spawn = dict(decision["spawn_arguments"])
    result = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "fork_turns": "none",
            "tool_input": {**spawn, "message": "Return a bounded verdict.", "fork_turns": "all"},
        },
        env,
    )

    block = blocking_payload(result.stdout)
    assert block is not None
    assert "validation failed" in str(block["reason"])


def test_routing_guard_allows_unmanaged_native_spawns_when_managed_route_pending(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    guard = configured_command("PreToolUse", "subagent_routing_pretool_guard.py")
    managed_session = "managed-recommendation-with-unrelated-spawns"
    run_configured_event(
        "UserPromptSubmit",
        prompt_payload(managed_session, high_complexity_prompt()),
        env,
    )
    for index, agent_type in enumerate(("ralph-reviewer", "ralph-tester", "ralph-security", "ralph-coder")):
        result = run_command(
            guard,
            {
                "hook_event_name": "PreToolUse",
                "session_id": managed_session,
                "cwd": str(ROOT),
                "tool_name": "spawn_agent",
                "prompt": "benign parent context " * (600),
                "tool_input": {
                    "agent_type": agent_type,
                    "task_name": "unclassified_lane",
                    "fork_turns": "none",
                    "route": "other",
                    "message": "Review this bounded, unrelated task.",
                },
            },
            env,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""


def test_routing_guard_blocks_unmanaged_history_even_with_green_task_state(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    session_id = "generic-history-green-state"
    run_configured_event(
        "UserPromptSubmit",
        prompt_payload(session_id, high_complexity_prompt()),
        env,
    )
    result = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "tool_input": {
                "agent_type": "ralph-reviewer",
                "task_name": "unclassified_lane",
                "fork_turns": "all",
                "message": "The brief is benign, but history must not be inherited.",
            },
        },
        env,
    )

    block = blocking_payload(result.stdout)
    assert block is not None
    assert "fork_turns=none" in str(block["reason"])


def test_routing_guard_blocks_managed_spawn_without_routing_state(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    guard = configured_command("PreToolUse", "subagent_routing_pretool_guard.py")
    result = run_command(
        guard,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "managed-native-spawn-without-state",
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "tool_input": {
                "agent_type": "sol-advisor",
                "task_name": "sol_advisor",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "fork_turns": "none",
            },
        },
        env,
    )

    assert result.returncode == 0, result.stderr
    block = blocking_payload(result.stdout)
    assert block is not None
    assert "routing state" in str(block["reason"])


def test_routing_guard_blocks_sol_spawn_after_live_budget_exhaustion(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    session_id = "sol-budget-exhausted"
    run_configured_event("UserPromptSubmit", prompt_payload(session_id, high_complexity_prompt()), env)
    _, decision = routing_state(env, session_id)
    spawn_arguments = dict(decision["spawn_arguments"])

    for phase, agent_id in (("plan", "sol-budget-plan"), ("stuck", "sol-budget-stuck")):
        if phase == "stuck":
            for command in ("pytest --first-failure", "pytest --second-failure"):
                run_configured_event(
                    "PostToolUse",
                    {
                        "hook_event_name": "PostToolUse",
                        "session_id": session_id,
                        "cwd": str(ROOT),
                        "success": False,
                        "command": command,
                    },
                    env,
                )
        run_configured_event(
            "SubagentStart",
            {
                "hook_event_name": "SubagentStart",
                "session_id": session_id,
                "cwd": str(ROOT),
                "phase": phase,
                "agent_id": agent_id,
                **spawn_arguments,
            },
            env,
        )

    exhausted_state, _ = routing_state(env, session_id)
    assert exhausted_state["consultation_count"] == 2
    assert exhausted_state["budget_remaining"] == 0

    guard = configured_command("PreToolUse", "subagent_routing_pretool_guard.py")
    result = run_command(
        guard,
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "tool_input": {
                **spawn_arguments,
                "message": "This third consultation must be rejected.",
            },
        },
        env,
    )

    assert result.returncode == 0, result.stderr
    block = blocking_payload(result.stdout)
    assert block is not None
    assert "budget" in str(block["reason"]).lower()


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


def test_sol_pretool_reservation_blocks_duplicate_and_releases_failed_spawn(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    session_id = "sol-phase-reservation"
    run_configured_event("UserPromptSubmit", prompt_payload(session_id, high_complexity_prompt()), env)
    _, decision = routing_state(env, session_id)
    spawn = {
        **dict(decision["spawn_arguments"]),
        "message": "Review this bounded decision and return a compact verdict.",
    }
    base = {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "cwd": str(ROOT),
        "tool_name": "spawn_agent",
        "tool_input": spawn,
    }

    def run_pretool(payload: dict[str, object]) -> list[subprocess.CompletedProcess[str]]:
        return run_configured_event("PreToolUse", payload, env)

    invalid_results = run_pretool(
        {
            **base,
            "tool_input": {**spawn, "reasoning_effort": "xhigh"},
        }
    )
    invalid_block = next(
        (blocking_payload(result.stdout) for result in invalid_results if blocking_payload(result.stdout)),
        None,
    )
    assert invalid_block is not None
    assert "effort" in str(invalid_block["reason"])
    invalid_state, _ = routing_state(env, session_id)
    assert invalid_state["phase_reservations"] == {}

    first_results = run_pretool(base)
    assert all(blocking_payload(result.stdout) is None for result in first_results)
    first_state, _ = routing_state(env, session_id)
    assert first_state["consultation_count"] == 0
    assert first_state["phase_reservations"]["plan"]

    duplicate_results = run_pretool(base)
    duplicate_block = next(
        (blocking_payload(result.stdout) for result in duplicate_results if blocking_payload(result.stdout)),
        None,
    )
    assert duplicate_block is not None
    assert "already reserved" in str(duplicate_block["reason"])

    run_command(
        configured_command("PostToolUse", "sol_advisor_observer.py"),
        {
            "hook_event_name": "PostToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "success": False,
            "command": "spawn_agent unrelated failure",
            "tool_input": {
                "agent_type": "ralph-reviewer",
                "task_name": "unrelated_lane",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "high",
            },
        },
        env,
    )
    still_reserved_results = run_pretool(base)
    still_reserved_block = next(
        (blocking_payload(result.stdout) for result in still_reserved_results if blocking_payload(result.stdout)),
        None,
    )
    assert still_reserved_block is not None
    assert "already reserved" in str(still_reserved_block["reason"])

    run_command(
        configured_command("PostToolUse", "sol_advisor_observer.py"),
        {
            "hook_event_name": "PostToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "success": False,
            "command": "spawn_agent failed before start",
            "tool_input": spawn,
        },
        env,
    )

    retry_results = run_pretool(base)
    assert all(blocking_payload(result.stdout) is None for result in retry_results)


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
    red_state = json.loads(state_path(env, session_id).read_text(encoding="utf-8"))
    assert red_state["sensitivity"] == "RED"
    assert red_state["routing"]["subagent_route"] == "none"
    assert not any("Sol advisor eligibility: yes" in context for context in context_values(results))

    inherited_history = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "tool_input": {
                "agent_type": "ralph-reviewer",
                "task_name": "reviewer",
                "fork_turns": "all",
                "message": "The explicit brief is benign, but history must not be inherited.",
            },
        },
        env,
    )
    inherited_block = blocking_payload(inherited_history.stdout)
    assert inherited_block is not None
    assert "RED-sensitive task state" in str(inherited_block["reason"])

    generated = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert red_marker not in generated
    assert_sources_unchanged(snapshot)


def test_routing_guard_blocks_a_red_brief_before_managed_spawn(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    session_id = "sol-red-brief"
    run_configured_event(
        "UserPromptSubmit",
        prompt_payload(session_id, high_complexity_prompt()),
        env,
    )
    _state, decision = routing_state(env, session_id)
    spawn_arguments = dict(decision["spawn_arguments"])
    red_marker = "api" + "_key" + "=brief-red-sentinel"
    result = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "tool_input": {**spawn_arguments, "message": f"Include {red_marker} in the advisor brief."},
        },
        env,
    )

    assert result.returncode == 0
    block = blocking_payload(result.stdout)
    assert block is not None
    assert "RED-sensitive subagent brief" in str(block["reason"])

    missing_brief = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "tool_input": spawn_arguments,
        },
        env,
    )
    missing_block = blocking_payload(missing_brief.stdout)
    assert missing_block is not None
    assert "decision brief" in str(missing_block["reason"])
    missing_state, _missing_decision = routing_state(env, session_id)
    assert missing_state["consultation_count"] == 0

    aggregate_brief = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "tool_input": {
                **spawn_arguments,
                "message": "a" * 4_500,
                "brief": "b" * 4_000,
            },
        },
        env,
    )
    aggregate_block = blocking_payload(aggregate_brief.stdout)
    assert aggregate_block is not None
    assert "bounded context limit" in str(aggregate_block["reason"])

    mirrored_brief = "m" * 4_500
    mirrored_result = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "message": mirrored_brief,
            "tool_input": {**spawn_arguments, "message": mirrored_brief},
        },
        env,
    )
    assert blocking_payload(mirrored_result.stdout) is None

    generic_result = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "prompt": "This top-level description is benign.",
            "tool_input": {
                "agent_type": "ralph-reviewer",
                "task_name": "reviewer",
                "message": f"Do not forward {red_marker} to the reviewer.",
            },
        },
        env,
    )
    generic_block = blocking_payload(generic_result.stdout)
    assert generic_block is not None
    assert "RED-sensitive subagent brief" in str(generic_block["reason"])

    red_state_session = "sol-red-persisted-state"
    run_configured_event(
        "UserPromptSubmit",
        {
            **prompt_payload(red_state_session, "Review this task locally."),
            "sensitivity": "RED",
        },
        env,
        commands=[configured_command("UserPromptSubmit", "sol_advisor_prompt_state.py")],
    )
    persisted_red_result = run_command(
        configured_command("PreToolUse", "subagent_routing_pretool_guard.py"),
        {
            "hook_event_name": "PreToolUse",
            "session_id": red_state_session,
            "cwd": str(ROOT),
            "tool_name": "spawn_agent",
            "prompt": "Benign parent envelope.",
            "tool_input": {
                "agent_type": "ralph-reviewer",
                "task_name": "reviewer",
                "fork_turns": "all",
                "message": "Review the bounded local task.",
            },
        },
        env,
    )
    persisted_red_block = blocking_payload(persisted_red_result.stdout)
    assert persisted_red_block is not None
    assert "RED-sensitive task state" in str(persisted_red_block["reason"])
