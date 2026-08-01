from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.sol_advisor import (
    initialize,
    is_sol_advisor,
    mark_advisor,
    mark_stop_guard,
    stop_review_recommendation_pending,
    observe_failure,
    read_state,
    state_path,
    executor_context,
    has_completion_evidence,
    has_fork_metadata,
    has_no_history_fork,
    decision_fingerprint,
)
from shared.tool_result import success_from_payload


def payload(tmp_path: Path, **extra: object) -> dict[str, object]:
    return {
        "cwd": str(ROOT),
        "session_id": "sol-advisor-test",
        "complexity": 1,
        **extra,
    }


def test_material_low_complexity_task_stays_local_without_explicit_sol_request(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Review an authorization migration decision.")

    state = initialize(event)

    assert state is not None
    assert state["complexity"] == 1
    assert state["routing"]["effective_complexity"] == 4
    assert state["routing"]["subagent_route"] == "none"
    assert state["final_review_eligible"] is False
    assert state["consultation_eligible"] is False
    persisted = state_path(event).read_text(encoding="utf-8")
    assert "authorization" in persisted
    assert "Review an authorization migration decision." not in persisted


def test_routine_task_stays_local_and_does_not_consult_sol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Explain the repository status in one paragraph.")

    state = initialize(event)

    assert state is not None
    assert state["consultation_eligible"] is False
    assert state["final_review_eligible"] is False
    assert state["consultation_count"] == 0
    assert executor_context(state) == ""
    assert stop_review_recommendation_pending(state) is False


def test_neutral_workspace_records_luna_fallback_as_global_executor_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    event = {
        "cwd": str(tmp_path / "workspace-without-config"),
        "session_id": "fallback-source",
        "complexity": 1,
        "prompt": "Explain the repository status in one paragraph.",
    }

    state = initialize(event)

    assert state is not None
    assert state["routing"]["configured_executor_model"] == "gpt-5.6-luna"
    assert state["routing"]["configured_executor_effort"] == "max"
    assert state["routing"]["configured_executor_source"] == "fallback"


def test_neutral_workspace_reads_global_executor_config_when_present(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "global-test-model"\nmodel_reasoning_effort = "high"\n', encoding="utf-8"
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    state = initialize(
        {
            "cwd": str(tmp_path / "neutral"),
            "session_id": "global-source",
            "complexity": 1,
            "prompt": "Explain the repository status.",
        }
    )

    assert state is not None
    assert state["routing"]["configured_executor_model"] == "global-test-model"
    assert state["routing"]["configured_executor_source"] == "global"


def test_nested_repository_cwd_reads_the_repository_executor_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    (repository / ".codex").mkdir()
    (repository / ".codex" / "config.toml").write_text(
        'model = "nested-repo-model"\nmodel_reasoning_effort = "max"\n', encoding="utf-8"
    )
    nested = repository / "packages" / "feature"
    nested.mkdir(parents=True)
    state = initialize(
        {
            "cwd": str(nested),
            "session_id": "nested-repo-source",
            "complexity": 1,
            "prompt": "Explain the repository status.",
        }
    )

    assert state is not None
    assert state["routing"]["configured_executor_model"] == "nested-repo-model"
    assert state["routing"]["configured_executor_source"] == "repository"


def test_two_distinct_failures_make_an_existing_material_task_stuck_eligible(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Decide the rollout architecture.")
    initialize(event)

    observe_failure({**event, "success": False, "command": "test first hypothesis"})
    result = observe_failure({**event, "success": False, "command": "test second hypothesis"})

    assert result["failure_count"] == 2
    assert result["stuck_eligible"] is True
    assert len(result["failure_fingerprints"]) == 2


def test_stop_guard_is_one_time_and_skips_completed_advice(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, complexity=8, prompt="Choose a database schema migration path.")
    initialize(event)
    state = read_state(event)
    assert stop_review_recommendation_pending(state) is True

    mark_stop_guard(event)
    assert stop_review_recommendation_pending(read_state(event)) is True

    event2 = {**event, "session_id": "sol-advisor-complete"}
    initialize(event2)
    mark_advisor(event2, completed=False)
    mark_advisor(event2, completed=True)
    assert stop_review_recommendation_pending(read_state(event2)) is False


def test_continuation_keeps_existing_consultation_budget(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Choose an external interface architecture.")
    initialize(event)
    mark_advisor(event, completed=False)

    continued = initialize({**event, "prompt": "continua con la validación"})

    assert continued is not None
    assert continued["consultation_count"] == 1
    assert continued["advisor_started"] is True
    assert continued["decision_fingerprint"] == decision_fingerprint(continued)


def test_continuation_can_raise_monotonic_complexity_and_refresh_the_lane(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, complexity=1, prompt="Explain the repository status.")
    initialize(event)

    continued = initialize(
        {
            **event,
            "complexity": 8,
            "intent": "architecture",
            "prompt": "continua: diseña ahora la arquitectura de migración.",
        }
    )

    assert continued is not None
    assert continued["complexity"] == 8
    assert continued["routing"]["subagent_route"] == "sol-advisor"


def test_continuation_reuses_validated_active_analysis_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(
        tmp_path,
        complexity=9,
        intent="architecture",
        active_analysis_enabled=True,
        bounded_scope=True,
        local_verification_available=True,
        hard_gates_pass=True,
        budget_class="small",
        task_subagent_override={"route": "sol-active-analysis", "reasoning_effort": "xhigh"},
        prompt="Validate this bounded architecture decision.",
    )

    initial = initialize(event)
    assert initial is not None
    assert initial["routing"]["subagent_route"] == "sol-active-analysis"
    assert initial["routing"]["active_analysis_eligible"] is True

    continuation_payload = {
        key: value
        for key, value in event.items()
        if key
        not in {
            "active_analysis_enabled",
            "bounded_scope",
            "local_verification_available",
            "hard_gates_pass",
            "budget_class",
            "task_subagent_override",
            "prompt",
        }
    }
    continued = initialize({**continuation_payload, "prompt": "continua con la validación"})

    assert continued is not None
    assert continued["active_analysis_enabled"] is True
    assert continued["bounded_scope"] is True
    assert continued["local_verification_available"] is True
    assert continued["hard_gates_pass"] is True
    assert continued["budget_class"] == "small"
    assert continued["routing"]["subagent_route"] == "sol-active-analysis"
    assert continued["routing"]["active_analysis_eligible"] is True


def test_task_boundary_does_not_reuse_active_analysis_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(
        tmp_path,
        complexity=9,
        intent="architecture",
        active_analysis_enabled=True,
        bounded_scope=True,
        local_verification_available=True,
        budget_class="small",
        task_subagent_override={"route": "sol-active-analysis", "reasoning_effort": "xhigh"},
        prompt="Validate this bounded architecture decision.",
    )
    initial = initialize(event)
    assert initial is not None

    fresh_payload = {
        key: value
        for key, value in event.items()
        if key
        not in {
            "active_analysis_enabled",
            "bounded_scope",
            "local_verification_available",
            "budget_class",
            "task_subagent_override",
            "prompt",
        }
    }
    fresh = initialize(
        {
            **fresh_payload,
            "new_task": True,
            "prompt": "continua con una nueva tarea de arquitectura",
        }
    )

    assert fresh is not None
    assert fresh["task_id"] != initial["task_id"]
    assert fresh["active_analysis_enabled"] is False
    assert fresh["routing"]["subagent_route"] == "sol-advisor"
    assert fresh["routing"]["active_analysis_eligible"] is False


def test_invalid_or_failed_hard_gates_cannot_reactivate_active_analysis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(
        tmp_path,
        complexity=9,
        intent="architecture",
        active_analysis_enabled=True,
        bounded_scope=True,
        local_verification_available=True,
        hard_gates_pass=True,
        budget_class="small",
        task_subagent_override={"route": "sol-active-analysis", "reasoning_effort": "xhigh"},
        prompt="Validate this bounded architecture decision.",
    )
    initialize(event)

    failed = initialize({**event, "hard_gates_pass": False, "prompt": "continua: hard gates failed"})
    assert failed is not None
    assert failed["hard_gates_pass"] is False
    assert failed["routing"]["subagent_route"] == "sol-advisor"
    assert failed["routing"]["active_analysis_eligible"] is False

    omitted = {
        key: value for key, value in event.items() if key not in {"hard_gates_pass", "prompt"}
    }
    invalid = initialize({**omitted, "hard_gates_pass": "bogus", "prompt": "continua: retry"})
    assert invalid is not None
    assert invalid["hard_gates_pass"] is False
    assert invalid["routing"]["active_analysis_eligible"] is False


def test_continuation_reuses_bounded_task_and_session_overrides(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(
        tmp_path,
        complexity=8,
        prompt="Choose an authorization architecture for rollout.",
        task_subagent_override={
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "expires_at": 4_102_444_800,
        },
        session_subagent_override={"model": "gpt-5.6-terra", "reasoning_effort": "high"},
    )

    state = initialize(event)
    assert state is not None
    assert state["routing"]["subagent_route"] == "sol-advisor"

    continuation_payload = {
        key: value
        for key, value in event.items()
        if key not in {"task_subagent_override", "session_subagent_override", "prompt"}
    }
    continued = initialize({**continuation_payload, "prompt": "continua con la validación"})

    assert continued is not None
    assert continued["task_subagent_override"]["model"] == "gpt-5.6-sol"
    assert continued["session_subagent_override"]["model"] == "gpt-5.6-terra"
    assert continued["routing"]["subagent_route"] == "sol-advisor"

    ordinary = initialize({**continuation_payload, "prompt": "status update"})
    assert ordinary is not None
    assert ordinary["routing"]["subagent_route"] == "sol-advisor"
    assert ordinary["task_subagent_override"]["model"] == "gpt-5.6-sol"


def test_session_override_survives_an_explicit_task_boundary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(
        tmp_path,
        complexity=1,
        prompt="Explain the repository status in one paragraph.",
        session_subagent_override={"model": "gpt-5.6-terra", "reasoning_effort": "high"},
    )
    initialize(event)

    fresh = initialize(
        {
            **event,
            "new_task": True,
            "complexity": 4,
            "intent": "implementation",
            "prompt": "Implement the bounded migration change.",
            "session_subagent_override": None,
        }
    )

    assert fresh is not None
    assert fresh["task_subagent_override"] is None
    assert fresh["session_subagent_override"]["model"] == "gpt-5.6-terra"
    assert fresh["routing"]["subagent_route"] == "terra-implementation"


def test_red_sensitivity_is_sticky_across_a_continuation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(
        tmp_path,
        complexity=8,
        sensitivity="RED",
        prompt="Review this bounded architecture decision locally.",
    )

    state = initialize(event)
    assert state is not None
    assert state["sensitivity"] == "RED"
    assert state["routing"]["subagent_route"] == "none"

    continued = initialize({**event, "prompt": "continua con el estado actual"})

    assert continued is not None
    assert continued["sensitivity"] == "RED"
    assert continued["routing"]["sensitivity"] == "RED"
    assert continued["routing"]["subagent_route"] == "none"

    natural_boundary = initialize({**event, "prompt": "start a new validation step"})
    assert natural_boundary is not None
    assert natural_boundary["sensitivity"] == "RED"

    fresh = initialize({**event, "new_task": True, "sensitivity": "GREEN", "prompt": "Start a routine task."})
    assert fresh is not None
    assert fresh["sensitivity"] == "GREEN"


def test_red_prompt_replaces_prior_route_without_persisting_prompt_content(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, complexity=8, prompt="Choose an authorization architecture for rollout.")
    initial = initialize(event)
    assert initial is not None
    assert initial["routing"]["subagent_route"] == "sol-advisor"

    red_marker = "api" + "_key" + "=red-state-sentinel"
    red = initialize({**event, "prompt": f"Keep this local: {red_marker}"})

    assert red is not None
    assert red["sensitivity"] == "RED"
    assert red["routing"]["subagent_route"] == "none"
    persisted = state_path(event).read_text(encoding="utf-8")
    assert red_marker not in persisted


def test_nested_yellow_classification_cannot_be_downgraded_by_top_level_green(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    state = initialize(
        payload(
            tmp_path,
            prompt="Review this bounded architecture decision.",
            sensitivity="GREEN",
            task_intake={"sensitivity": "YELLOW"},
        )
    )

    assert state is not None
    assert state["sensitivity"] == "YELLOW"
    assert state["routing"]["sensitivity"] == "YELLOW"


def test_low_impact_followup_preserves_pending_review(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, complexity=8, prompt="Choose an authorization architecture for rollout.")
    initialize(event)

    continued = initialize({**event, "prompt": "status update"})

    assert continued is not None
    assert continued["final_review_eligible"] is True
    assert continued["advisor_completed"] is False
    assert stop_review_recommendation_pending(read_state(event)) is True


def test_low_impact_followup_preserves_completed_review(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, complexity=8, prompt="Choose an authorization architecture for rollout.")
    initialize(event)
    mark_advisor(event, completed=True)

    continued = initialize({**event, "prompt": "status update"})

    assert continued is not None
    assert continued["final_review_eligible"] is True
    assert continued["advisor_completed"] is True
    assert stop_review_recommendation_pending(continued) is False


def test_material_followup_keeps_budget_and_invalidates_changed_verdict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, complexity=8, prompt="Choose an authorization architecture for rollout.")
    initialize(event)
    mark_advisor({**event, "phase": "plan"}, completed=False)
    mark_advisor({**event, "phase": "plan", "agent_id": "advisor-1"}, completed=True)

    continued = initialize({**event, "prompt": "Choose an authorization migration architecture for rollout."})

    assert continued is not None
    assert continued["consultation_count"] == 1
    assert continued["budget_remaining"] == 1
    assert continued["advisor_completed"] is False
    assert continued["prior_verdict_fingerprint"] != continued["decision_fingerprint"]


def test_explicit_new_task_starts_fresh_advisor_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Choose an authorization architecture for rollout.")
    initialize(event)
    mark_advisor(event, completed=True)

    fresh = initialize({**event, "new_task": True, "prompt": "Explain the repository status."})

    assert fresh is not None
    assert fresh["final_review_eligible"] is False
    assert fresh["advisor_completed"] is False
    assert stop_review_recommendation_pending(fresh) is False


def test_failure_observer_uses_exit_code_result_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Decide the rollout architecture.")
    initialize(event)

    observe_failure({**event, "exit_code": 1, "command": "first failing hypothesis"})
    result = observe_failure({**event, "returncode": 2, "command": "second failing hypothesis"})

    assert result["failure_count"] == 2
    assert result["stuck_eligible"] is True


def test_tool_result_normalization_preserves_unknown_and_success_states() -> None:
    assert success_from_payload({"exit_code": 1}) is False
    assert success_from_payload({"returncode": 0}) is True
    assert success_from_payload({"tool_response": {"return_code": 1}}) is False
    assert success_from_payload({"success": True, "exit_code": 1}) is True
    assert success_from_payload({"exit_code": "1"}) is None
    assert success_from_payload({}) is None


def test_state_record_tracks_task_phase_fingerprint_and_budget(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Choose an authorization architecture for rollout.")

    state = initialize(event)

    assert state is not None
    assert state["version"] == 2
    assert state["task_id"]
    assert state["phase"] == "plan"
    assert state["decision_fingerprint"]
    assert state["consultation_budget"] == 2
    assert state["budget_remaining"] == 2
    assert state["prior_verdict_ref"] == ""


def test_equivalent_advisor_start_reuses_prior_verdict_and_budget(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Choose an authorization architecture for rollout.")
    initialize(event)

    first = mark_advisor({**event, "phase": "plan"}, completed=False)
    mark_advisor(
        {**event, "phase": "plan", "agent_id": "advisor-1", "success": True},
        completed=True,
    )
    reused = mark_advisor({**event, "phase": "plan"}, completed=False)

    assert first["consultation_count"] == 1
    assert reused["consultation_count"] == 1
    assert reused["budget_remaining"] == 1
    assert reused["advisor_reused"] is True
    assert reused["prior_verdict_fingerprint"] == reused["decision_fingerprint"]
    assert reused["prior_verdict_ref"]


def test_new_failure_evidence_allows_one_stuck_phase_consultation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, prompt="Decide the rollout architecture.")
    initialize(event)
    mark_advisor({**event, "phase": "plan"}, completed=False)
    mark_advisor({**event, "phase": "plan"}, completed=True)

    observe_failure({**event, "success": False, "command": "first hypothesis"})
    observe_failure({**event, "success": False, "command": "second hypothesis"})
    stuck = mark_advisor({**event, "phase": "stuck"}, completed=False)

    assert stuck["phase"] == "stuck"
    assert stuck["consultation_count"] == 2
    assert stuck["budget_remaining"] == 0
    assert stuck["consulted_phases"]["plan"]
    assert stuck["consulted_phases"]["stuck"] == stuck["decision_fingerprint"]


def test_stuck_transition_refreshes_routing_from_current_failure_payload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, complexity=4, prompt="Decide the rollout architecture.")
    initialize(event)

    observe_failure({**event, "success": False, "command": "first hypothesis"})
    refreshed = observe_failure(
        {
            **event,
            "success": False,
            "command": "second hypothesis",
            "task_subagent_override": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
        }
    )

    assert refreshed["phase"] == "stuck"
    assert refreshed["routing"]["subagent_route"] == "sol-advisor"
    assert refreshed["routing"]["reason_code"] == "explicit-advisor-override"

    continued = initialize({**event, "prompt": "status update"})
    assert continued is not None
    assert continued["task_subagent_override"]["model"] == "gpt-5.6-sol"
    assert continued["routing"]["subagent_route"] == "sol-advisor"


def test_final_review_reuses_equivalent_prior_verdict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, complexity=8, prompt="Choose a database schema migration path.")
    initialize(event)
    mark_advisor({**event, "phase": "plan", "agent_id": "advisor-1"}, completed=False)
    mark_advisor({**event, "phase": "plan", "agent_id": "advisor-1", "success": True}, completed=True)

    state = read_state(event)

    assert stop_review_recommendation_pending(state) is False
    assert state["prior_verdict_phase"] == "plan"


def test_final_phase_consumes_remaining_budget_after_changed_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "state"))
    event = payload(tmp_path, complexity=8, prompt="Choose a database schema migration path.")
    initialize(event)
    mark_advisor({**event, "phase": "plan"}, completed=False)
    mark_advisor({**event, "phase": "plan"}, completed=True)
    observe_failure({**event, "success": False, "command": "first hypothesis"})
    observe_failure({**event, "success": False, "command": "second hypothesis"})

    state = read_state(event)
    assert stop_review_recommendation_pending(state) is True
    mark_stop_guard(event)
    started = mark_advisor({**event, "phase": "final"}, completed=False)
    completed = mark_advisor(
        {**event, "phase": "final", "agent_id": "advisor-final", "success": True},
        completed=True,
    )

    assert started["consultation_count"] == 2
    assert completed["prior_verdict_phase"] == "final"
    assert stop_review_recommendation_pending(completed) is False


def test_name_or_model_identifies_the_native_sol_advisor() -> None:
    assert is_sol_advisor({"agent_type": "sol-advisor"}) is True
    assert is_sol_advisor({"agentType": "sol_advisor"}) is True
    assert is_sol_advisor({"tool_input": {"task_name": "sol_advisor", "model": "gpt-5.6-sol"}}) is True
    assert is_sol_advisor({"subagent": {"modelName": "gpt-5.6-sol"}}) is True
    assert is_sol_advisor({"agent_name": "ralph-reviewer"}) is False


def test_typed_advisor_requires_an_explicit_no_history_fork() -> None:
    assert has_no_history_fork({"tool_input": {"agent_type": "sol-advisor", "fork_turns": "none"}}) is True
    assert has_no_history_fork({"tool_input": {"agent_type": "sol-advisor", "fork_turns": "all"}}) is False
    assert has_fork_metadata({"tool_input": {"agent_type": "sol-advisor", "fork_turns": "all"}}) is True
    assert has_fork_metadata({"tool_input": {"agent_type": "sol-advisor"}}) is False


def test_advisor_completion_requires_success_and_an_execution_identity() -> None:
    assert has_completion_evidence({"success": True, "agent_id": "agent-1"}) is True
    assert has_completion_evidence({"success": True, "agent_type": "sol-advisor"}) is False
    assert has_completion_evidence({"success": False, "agent_id": "agent-1"}) is False


def test_executor_context_requires_a_minimized_no_history_advisor_fork() -> None:
    context = executor_context(
        {
            "consultation_eligible": True,
            "complexity": 8,
            "impact_reasons": ["migration"],
            "routing": {
                "subagent_route": "sol-advisor",
                "effective_complexity": 8,
                "configured_executor_model": "gpt-5.6-luna",
                "configured_executor_effort": "max",
                "spawn_arguments": {
                    "agent_type": "sol-advisor",
                    "task_name": "sol_advisor",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "high",
                    "fork_turns": "none",
                },
            },
        }
    )

    assert "spawn_agent" in context
    assert "fork_turns=`none`" in context
    assert "model=`gpt-5.6-sol`" in context
    assert "compact decision brief" in context


def test_executor_context_exposes_the_bounded_terra_implementation_contract() -> None:
    context = executor_context(
        {
            "consultation_eligible": True,
            "complexity": 4,
            "routing": {
                "subagent_route": "terra-implementation",
                "effective_complexity": 4,
                "intent": "implementation",
                "configured_executor_model": "gpt-5.6-luna",
                "configured_executor_effort": "max",
            },
        }
    )

    assert "Terra implementation is eligible" in context
    assert "agent_type=`ralph-coder`" in context
    assert "task_name=`terra_implementation`" in context
    assert "model=`gpt-5.6-terra`" in context
    assert "reasoning_effort=`high`" in context


def test_sol_advisor_skill_contract_is_bounded_and_model_agnostic() -> None:
    skill = (ROOT / ".agents" / "skills" / "sol-advisor" / "SKILL.md").read_text(encoding="utf-8")

    assert "GPT-5.6 Terra or Luna" in skill
    assert "at most one consultation per phase and two per task" in skill
    assert "`plan`, `stuck`, or `final`" in skill
    assert "fresh, no-history fork" in skill
    assert "300 words" in (ROOT / ".codex" / "agents" / "sol-advisor.toml").read_text(encoding="utf-8")


def test_high_impact_lifecycle_enforces_fresh_fork_and_releases_completion(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(state_root))
    event = payload(tmp_path, complexity=8, prompt="Choose an authorization architecture for a public rollout.")
    initialize(event)

    def run_hook(name: str, hook_payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HOOKS / name)],
            cwd=ROOT,
            input=json.dumps(hook_payload),
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "CODEX_HOOK_STATE_ROOT": str(state_root)},
        )

    wrong_fork = run_hook(
        "sol_advisor_pretool_guard.py",
        {**event, "tool_input": {"task_name": "sol_advisor", "model": "gpt-5.6-sol", "fork_turns": "all"}},
    )
    assert wrong_fork.returncode == 0
    assert json.loads(wrong_fork.stdout)["decision"] == "block"

    omitted_fork = run_hook(
        "sol_advisor_pretool_guard.py",
        {**event, "tool_input": {"task_name": "sol_advisor", "model": "gpt-5.6-sol"}},
    )
    assert omitted_fork.returncode == 0
    assert omitted_fork.stdout == ""

    waiting = run_hook("sol_advisor_stop_guard.py", event)
    assert waiting.returncode == 0
    assert waiting.stdout == ""
    assert read_state(event)["stop_guard_issued"] is True

    completed = run_hook(
        "sol_advisor_subagent_stop.py",
        {**event, "task_name": "sol_advisor", "model": "gpt-5.6-sol", "agent_id": "advisor-run-1", "success": True},
    )
    assert completed.returncode == 0
    released = run_hook("sol_advisor_stop_guard.py", event)
    assert released.returncode == 0
    assert released.stdout == ""
