from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.subagent_routing import (
    LUNA_DEFAULT_EFFORT,
    LUNA_MODEL,
    SOL_MODEL,
    TERRA_MODEL,
    ExecutorDefaults,
    RoutingBudget,
    RoutingCapabilities,
    RoutingRequest,
    SubagentOverride,
    resolve_subagent_routing,
)

REPOSITORY_DEFAULT = ExecutorDefaults(LUNA_MODEL, LUNA_DEFAULT_EFFORT)


def resolve(**changes: object):
    values: dict[str, object] = {
        "repository_default": REPOSITORY_DEFAULT,
        "raw_complexity": 1,
        "intent": "routine",
    }
    values.update(changes)
    return resolve_subagent_routing(RoutingRequest(**values))


@pytest.mark.parametrize(
    ("raw", "intent", "route", "effort", "spawn", "reason"),
    [
        (1, "routine", "none", None, False, "routine-luna-only"),
        (3, "implementation", "none", None, False, "routine-luna-only"),
        (4, "implementation", "terra-implementation", "high", True, "implementation-4-6"),
        (6, "implementation", "terra-implementation", "high", True, "implementation-4-6"),
        (7, "routine", "sol-advisor", "high", True, "sol-advisor-7-8"),
        (8, "routine", "sol-advisor", "high", True, "sol-advisor-7-8"),
        (8, "architecture", "sol-advisor", "high", True, "sol-advisor-7-8"),
        (9, "migration", "sol-advisor", "xhigh", True, "sol-advisor-9"),
        (10, "security", "sol-advisor", "max", True, "sol-advisor-10"),
    ],
)
def test_default_bands_are_deterministic(
    raw: int, intent: str, route: str, effort: str | None, spawn: bool, reason: str
) -> None:
    decision = resolve(raw_complexity=raw, intent=intent)

    assert decision.raw_complexity == raw
    assert decision.effective_complexity == raw
    assert decision.subagent_route == route
    assert decision.subagent_effort == effort
    assert decision.spawn_required is spawn
    assert decision.reason_code == reason
    assert decision.configured_executor_model == LUNA_MODEL
    assert decision.configured_executor_effort == LUNA_DEFAULT_EFFORT


def test_complexity_seven_and_eight_share_the_sol_advisor_lane() -> None:
    seven = resolve(raw_complexity=7, intent="routine")
    eight = resolve(raw_complexity=8, intent="routine")

    assert seven.subagent_route == eight.subagent_route == "sol-advisor"
    assert seven.subagent_effort == eight.subagent_effort == "high"
    assert seven.reason_code == eight.reason_code == "sol-advisor-7-8"
    assert seven.spawn_required is eight.spawn_required is True


def test_material_low_score_promotes_effective_band_without_automatic_delegation() -> None:
    decision = resolve(raw_complexity=3, intent="implementation", impact_class="material")

    assert decision.raw_complexity == 3
    assert decision.effective_complexity == 4
    assert decision.subagent_route == "none"
    assert decision.reason_code == "routine-luna-only"


def test_red_stays_local_even_when_an_override_requests_sol() -> None:
    decision = resolve(
        raw_complexity=10,
        intent="security",
        sensitivity="red",
        task_override=SubagentOverride(model=SOL_MODEL),
    )

    assert decision.subagent_route == "none"
    assert decision.subagent_model is None
    assert decision.spawn_required is False
    assert decision.reason_code == "red-local-only"
    assert decision.override_rejection_reason == "red-local-only"


def test_terra_route_exposes_only_real_spawn_arguments() -> None:
    decision = resolve(raw_complexity=4, intent="implementation")

    assert dict(decision.spawn_arguments) == {
        "agent_type": "ralph-coder",
        "fork_turns": "none",
        "model": TERRA_MODEL,
        "reasoning_effort": "high",
        "task_name": "terra_implementation",
    }
    with pytest.raises(TypeError):
        decision.spawn_arguments["model"] = SOL_MODEL  # type: ignore[index]


def test_task_override_wins_over_session_without_changing_executor() -> None:
    decision = resolve(
        raw_complexity=1,
        intent="routine",
        task_override=SubagentOverride(model=SOL_MODEL, reasoning_effort="high"),
        session_override=SubagentOverride(model=TERRA_MODEL),
    )

    assert decision.override_scope == "task"
    assert dict(decision.override_requested) == {"model": SOL_MODEL, "reasoning_effort": "high"}
    assert dict(decision.override_effective) == {
        "model": SOL_MODEL,
        "reasoning_effort": "high",
        "route": "sol-advisor",
    }
    assert decision.subagent_route == "sol-advisor"
    assert decision.configured_executor_model == LUNA_MODEL
    assert decision.configured_executor_effort == LUNA_DEFAULT_EFFORT


def test_expired_task_override_is_auditable_and_falls_back_to_local_policy() -> None:
    decision = resolve(
        raw_complexity=1,
        intent="routine",
        current_epoch=42,
        task_override=SubagentOverride(model=SOL_MODEL, expires_at=42),
    )

    assert decision.override_scope == "task"
    assert decision.override_expiry == 42
    assert dict(decision.override_requested) == {"model": SOL_MODEL}
    assert decision.override_rejection_reason == "override-expired"
    assert decision.subagent_route == "none"


@pytest.mark.parametrize(
    ("raw", "intent", "override", "expected_route", "expected_error"),
    [
        (7, "implementation", SubagentOverride(model=SOL_MODEL), "sol-advisor", None),
        (8, "architecture", SubagentOverride(model=SOL_MODEL, reasoning_effort="xhigh"), "sol-advisor", "sol-effort-exceeds-effective-complexity"),
        (8, "architecture", SubagentOverride(model=TERRA_MODEL, reasoning_effort="max"), "sol-advisor", "terra-effort-must-be-high"),
    ],
)
def test_supported_and_rejected_overrides_have_explicit_effects(
    raw: int,
    intent: str,
    override: SubagentOverride,
    expected_route: str,
    expected_error: str | None,
) -> None:
    decision = resolve(raw_complexity=raw, intent=intent, task_override=override)

    assert decision.subagent_route == expected_route
    assert decision.override_rejection_reason == expected_error


def test_active_analysis_is_never_automatic_and_requires_every_gate() -> None:
    disabled = resolve(raw_complexity=9, intent="architecture")
    missing_scope = resolve(
        raw_complexity=9,
        intent="architecture",
        capabilities=RoutingCapabilities(active_analysis=True),
        budget=RoutingBudget(remaining=1, explicit_class="small"),
        local_verification_available=True,
    )
    eligible = resolve(
        raw_complexity=9,
        intent="architecture",
        capabilities=RoutingCapabilities(active_analysis=True),
        budget=RoutingBudget(remaining=1, explicit_class="small"),
        bounded_scope=True,
        local_verification_available=True,
    )

    assert disabled.subagent_route == "sol-advisor"
    assert disabled.active_analysis_eligible is False
    assert disabled.active_analysis_rejection_reason == "active-analysis-capability-disabled"
    assert missing_scope.active_analysis_rejection_reason == "active-analysis-requires-bounded-scope"
    assert eligible.active_analysis_eligible is True
    assert eligible.subagent_route == "sol-advisor"


def test_active_analysis_override_is_limited_to_gated_nine_and_ten() -> None:
    request = {
        "intent": "architecture",
        "task_override": SubagentOverride(route="sol-active-analysis", reasoning_effort="xhigh"),
        "capabilities": RoutingCapabilities(active_analysis=True),
        "budget": RoutingBudget(remaining=1, explicit_class="small"),
        "bounded_scope": True,
        "local_verification_available": True,
    }

    too_low = resolve(raw_complexity=8, **request)
    accepted = resolve(raw_complexity=9, **request)

    assert too_low.subagent_route == "sol-advisor"
    assert too_low.override_rejection_reason == "active-analysis-gates-not-met"
    assert accepted.subagent_route == "sol-active-analysis"
    assert accepted.subagent_mode == "active-analysis"
    assert accepted.subagent_model == SOL_MODEL
    assert accepted.subagent_effort == "xhigh"
    assert dict(accepted.spawn_arguments)["task_name"] == "sol_advisor"
    assert "subagent_route" not in accepted.spawn_arguments


def test_budget_prevents_a_sol_spawn_but_retains_the_recommendation() -> None:
    decision = resolve(raw_complexity=10, intent="security", budget=RoutingBudget(remaining=0))

    assert decision.subagent_route == "sol-advisor"
    assert decision.spawn_required is False
    assert decision.reason_code == "budget-exhausted"
    assert dict(decision.spawn_arguments)["reasoning_effort"] == "max"


def test_platform_capability_precedes_an_explicit_spawn_override() -> None:
    decision = resolve(
        raw_complexity=4,
        intent="implementation",
        task_override=SubagentOverride(model=SOL_MODEL),
        capabilities=RoutingCapabilities(spawn_model_effort=False),
    )

    assert decision.subagent_route == "none"
    assert decision.spawn_required is False
    assert dict(decision.spawn_arguments) == {}
    assert decision.reason_code == "platform-spawn-model-effort-unavailable"
    assert decision.override_rejection_reason == "platform-spawn-model-effort-unavailable"


def test_fingerprint_is_stable_for_same_bounded_facts_and_changes_with_budget() -> None:
    first = resolve(raw_complexity=9, intent="migration", budget=RoutingBudget(remaining=2))
    equivalent = resolve(raw_complexity=9, intent="migration", budget=RoutingBudget(remaining=2))
    changed = resolve(raw_complexity=9, intent="migration", budget=RoutingBudget(remaining=1))

    assert first.decision_fingerprint == equivalent.decision_fingerprint
    assert first.decision_fingerprint != changed.decision_fingerprint


def test_executor_precedence_is_repository_then_global_and_never_mutates_inputs() -> None:
    global_default = ExecutorDefaults("global-model", "high")
    repo_default = ExecutorDefaults(LUNA_MODEL, LUNA_DEFAULT_EFFORT)
    original = {"model": repo_default.model, "reasoning_effort": repo_default.reasoning_effort}

    repository = resolve_subagent_routing(
        RoutingRequest(raw_complexity=1, intent="routine", repository_default=repo_default, global_default=global_default)
    )
    global_only = resolve_subagent_routing(
        RoutingRequest(raw_complexity=1, intent="routine", repository_default=None, global_default=global_default)
    )

    assert (repository.configured_executor_model, repository.configured_executor_source) == (LUNA_MODEL, "repository")
    assert (global_only.configured_executor_model, global_only.configured_executor_source) == ("global-model", "global")
    assert original == {"model": repo_default.model, "reasoning_effort": repo_default.reasoning_effort}
