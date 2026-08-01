"""Deterministic policy for newly spawned Codex subagents.

This module deliberately has no hook, filesystem, clock, or configuration I/O.
Callers provide the already-resolved executor defaults and the bounded Aristotle
classification.  Its result is a recommendation for a *new* subagent only;
it never changes the configured executor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from json import dumps
from types import MappingProxyType
from typing import Mapping

POLICY_VERSION = "subagent-routing-v1"
LUNA_MODEL = "gpt-5.6-luna"
TERRA_MODEL = "gpt-5.6-terra"
SOL_MODEL = "gpt-5.6-sol"
LUNA_DEFAULT_EFFORT = "max"
TERRA_EFFORT = "high"
SOL_EFFORTS = {8: "high", 9: "xhigh", 10: "max"}
EFFORT_RANK = {"high": 1, "xhigh": 2, "max": 3}
SUPPORTED_ROUTES = frozenset({"terra-implementation", "sol-advisor", "sol-active-analysis"})
DEEP_INTENTS = frozenset({"architecture", "debugging", "migration", "security", "high-impact-review"})


def _frozen_map(values: Mapping[str, object] | None = None) -> Mapping[str, object]:
    return MappingProxyType(dict(sorted((values or {}).items())))


@dataclass(frozen=True)
class ExecutorDefaults:
    """Configured executor values resolved by config precedence outside this helper."""

    model: str
    reasoning_effort: str


@dataclass(frozen=True)
class SubagentOverride:
    """A bounded task- or session-scoped request for a new subagent lane."""

    model: str | None = None
    reasoning_effort: str | None = None
    route: str | None = None
    expires_at: int | None = None


@dataclass(frozen=True)
class RoutingCapabilities:
    """Runtime facts proven during compatibility validation, never inferred here."""

    spawn_model_effort: bool = True
    active_analysis: bool = False


@dataclass(frozen=True)
class RoutingBudget:
    """The bounded consultation allowance supplied by lifecycle state."""

    remaining: int = 2
    explicit_class: str | None = None


@dataclass(frozen=True)
class RoutingRequest:
    raw_complexity: int
    intent: str
    impact_class: str = "none"
    sensitivity: str = "GREEN"
    repository_default: ExecutorDefaults | None = None
    global_default: ExecutorDefaults = field(
        default_factory=lambda: ExecutorDefaults(LUNA_MODEL, LUNA_DEFAULT_EFFORT)
    )
    task_override: SubagentOverride | None = None
    session_override: SubagentOverride | None = None
    current_epoch: int = 0
    capabilities: RoutingCapabilities = field(default_factory=RoutingCapabilities)
    budget: RoutingBudget = field(default_factory=RoutingBudget)
    bounded_scope: bool = False
    local_verification_available: bool = False
    hard_gates_pass: bool = True


@dataclass(frozen=True)
class RoutingDecision:
    policy_version: str
    raw_complexity: int
    effective_complexity: int
    intent: str
    impact_class: str
    sensitivity: str
    configured_executor_model: str
    configured_executor_effort: str
    configured_executor_source: str
    subagent_route: str
    subagent_model: str | None
    subagent_mode: str
    subagent_effort: str | None
    spawn_required: bool
    spawn_arguments: Mapping[str, object]
    active_analysis_eligible: bool
    active_analysis_rejection_reason: str | None
    override_scope: str
    override_requested: Mapping[str, object]
    override_effective: Mapping[str, object]
    override_rejection_reason: str | None
    override_expiry: int | None
    budget_remaining: int
    decision_fingerprint: str
    reason_code: str


def resolve_subagent_routing(request: RoutingRequest) -> RoutingDecision:
    """Resolve a bounded subagent recommendation without mutating request state."""
    raw = _complexity(request.raw_complexity)
    intent = _intent(request.intent)
    impact = _impact(request.impact_class)
    sensitivity = request.sensitivity.strip().upper()
    executor, executor_source = _executor_defaults(request)
    effective = 4 if raw <= 3 and impact == "material" else raw
    active_ok, active_reason = _active_analysis_status(request, effective, sensitivity)
    override, scope, requested, expiry, override_error = _selected_override(request)

    route, model, mode, effort, reason = _base_route(raw, effective, intent, sensitivity)
    effective_override: Mapping[str, object] = _frozen_map()
    if override is not None and override_error is None:
        routed = _apply_override(
            override,
            effective=effective,
            sensitivity=sensitivity,
            active_ok=active_ok,
            hard_gates_pass=request.hard_gates_pass,
        )
        if routed[0] is None:
            override_error = routed[4]
        else:
            route, model, mode, effort, reason = routed[:5]
            effective_override = _frozen_map(
                {"model": model, "reasoning_effort": effort, "route": route}
            )

    if sensitivity == "RED":
        route, model, mode, effort, reason = "none", None, "none", None, "red-local-only"
        effective_override = _frozen_map()
        if requested:
            override_error = "red-local-only"

    if route != "none" and not request.capabilities.spawn_model_effort:
        route, model, mode, effort = "none", None, "none", None
        reason = "platform-spawn-model-effort-unavailable"
        effective_override = _frozen_map()
        override_error = override_error or "platform-spawn-model-effort-unavailable"
        spawn_required, spawn_arguments = False, _frozen_map()
    else:
        spawn_required = route != "none" and (route == "terra-implementation" or request.budget.remaining > 0)
        if route != "none" and request.budget.remaining <= 0:
            reason = "budget-exhausted"
        spawn_arguments = _frozen_map(_spawn_arguments(route, model, effort))

    fingerprint = _fingerprint(
        raw=raw,
        effective=effective,
        intent=intent,
        impact=impact,
        sensitivity=sensitivity,
        executor=executor,
        route=route,
        model=model,
        mode=mode,
        effort=effort,
        scope=scope,
        requested=requested,
        effective_override=effective_override,
        active_ok=active_ok,
        active_reason=active_reason,
        override_error=override_error,
        override_expiry=expiry,
        capabilities=request.capabilities,
        explicit_budget=request.budget.explicit_class,
        budget=request.budget.remaining,
        reason=reason,
    )
    return RoutingDecision(
        policy_version=POLICY_VERSION,
        raw_complexity=raw,
        effective_complexity=effective,
        intent=intent,
        impact_class=impact,
        sensitivity=sensitivity,
        configured_executor_model=executor.model,
        configured_executor_effort=executor.reasoning_effort,
        configured_executor_source=executor_source,
        subagent_route=route,
        subagent_model=model,
        subagent_mode=mode,
        subagent_effort=effort,
        spawn_required=spawn_required,
        spawn_arguments=spawn_arguments,
        active_analysis_eligible=active_ok,
        active_analysis_rejection_reason=active_reason,
        override_scope=scope,
        override_requested=requested,
        override_effective=effective_override,
        override_rejection_reason=override_error,
        override_expiry=expiry,
        budget_remaining=max(0, request.budget.remaining),
        decision_fingerprint=fingerprint,
        reason_code=reason,
    )


def _complexity(value: int) -> int:
    if not 1 <= value <= 10:
        raise ValueError("raw_complexity must be between 1 and 10")
    return value


def _intent(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    aliases = {"read-only": "routine", "review": "high-impact-review", "implementation-support": "implementation"}
    return aliases.get(normalized, normalized or "routine")


def _impact(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return "material" if normalized in {"material", "high", "high-impact"} else "none"


def _executor_defaults(request: RoutingRequest) -> tuple[ExecutorDefaults, str]:
    if request.repository_default is not None:
        return request.repository_default, "repository"
    return request.global_default, "global"


def _base_route(raw: int, effective: int, intent: str, sensitivity: str) -> tuple[str, str | None, str, str | None, str]:
    if sensitivity == "RED":
        return "none", None, "none", None, "red-local-only"
    if raw <= 3:
        return "none", None, "none", None, "routine-luna-only"
    if effective in range(4, 7) and intent == "implementation":
        return "terra-implementation", TERRA_MODEL, "implementation", TERRA_EFFORT, "implementation-4-6"
    if effective == 7:
        return "none", None, "none", None, "transition-7-no-automatic-subagent"
    if effective >= 8 and intent in DEEP_INTENTS:
        effort = SOL_EFFORTS[min(effective, 10)]
        return "sol-advisor", SOL_MODEL, "advisor", effort, f"sol-advisor-{effective}"
    return "none", None, "none", None, "intent-does-not-qualify-for-automatic-subagent"


def _selected_override(request: RoutingRequest) -> tuple[SubagentOverride | None, str, Mapping[str, object], int | None, str | None]:
    candidate, scope = (request.task_override, "task") if request.task_override else (request.session_override, "session")
    if candidate is None:
        return None, "none", _frozen_map(), None, None
    requested = _frozen_map(
        {key: value for key, value in {"model": candidate.model, "reasoning_effort": candidate.reasoning_effort, "route": candidate.route}.items() if value is not None}
    )
    if candidate.expires_at is not None and candidate.expires_at <= request.current_epoch:
        return None, scope, requested, candidate.expires_at, "override-expired"
    return candidate, scope, requested, candidate.expires_at, None


def _active_analysis_status(request: RoutingRequest, effective: int, sensitivity: str) -> tuple[bool, str | None]:
    if sensitivity == "RED":
        return False, "red-local-only"
    if effective < 9:
        return False, "active-analysis-requires-effective-complexity-9"
    if not request.capabilities.active_analysis:
        return False, "active-analysis-capability-disabled"
    if not request.bounded_scope:
        return False, "active-analysis-requires-bounded-scope"
    if not request.local_verification_available:
        return False, "active-analysis-requires-local-verification"
    if not request.budget.explicit_class:
        return False, "active-analysis-requires-explicit-budget"
    if request.budget.remaining <= 0:
        return False, "budget-exhausted"
    return True, None


def _apply_override(
    override: SubagentOverride,
    *,
    effective: int,
    sensitivity: str,
    active_ok: bool,
    hard_gates_pass: bool,
) -> tuple[str | None, str | None, str, str | None, str]:
    route = override.route or _route_for_model(override.model)
    if route not in SUPPORTED_ROUTES:
        return None, None, "none", None, "unsupported-subagent-override"
    expected_model = TERRA_MODEL if route == "terra-implementation" else SOL_MODEL
    if override.model not in {None, expected_model}:
        return None, None, "none", None, "override-model-route-mismatch"
    if sensitivity == "RED":
        return None, None, "none", None, "red-local-only"
    if route == "terra-implementation":
        if override.reasoning_effort not in {None, TERRA_EFFORT}:
            return None, None, "none", None, "terra-effort-must-be-high"
        return route, TERRA_MODEL, "implementation", TERRA_EFFORT, "explicit-terra-override"
    if route == "sol-active-analysis" and not active_ok:
        return None, None, "none", None, "active-analysis-gates-not-met"
    effort, effort_error = _sol_effort(override.reasoning_effort, effective, hard_gates_pass)
    if effort_error:
        return None, None, "none", None, effort_error
    mode = "active-analysis" if route == "sol-active-analysis" else "advisor"
    return route, SOL_MODEL, mode, effort, f"explicit-{mode}-override"


def _route_for_model(model: str | None) -> str | None:
    if model == TERRA_MODEL:
        return "terra-implementation"
    if model == SOL_MODEL:
        return "sol-advisor"
    return None


def _sol_effort(requested: str | None, effective: int, hard_gates_pass: bool) -> tuple[str, str | None]:
    ceiling = SOL_EFFORTS[max(8, min(effective, 10))]
    effort = requested or ceiling
    if effort not in EFFORT_RANK:
        return ceiling, "unsupported-sol-effort"
    if EFFORT_RANK[effort] > EFFORT_RANK[ceiling]:
        return ceiling, "sol-effort-exceeds-effective-complexity"
    if EFFORT_RANK[effort] < EFFORT_RANK[ceiling] and not hard_gates_pass:
        return ceiling, "sol-effort-downgrade-requires-hard-gates"
    return effort, None


def _spawn_arguments(route: str, model: str | None, effort: str | None) -> dict[str, object]:
    if route == "none" or model is None or effort is None:
        return {}
    is_terra = route == "terra-implementation"
    return {
        "agent_type": "ralph-coder" if is_terra else "sol-advisor",
        "fork_turns": "none",
        "model": model,
        "reasoning_effort": effort,
        "task_name": "terra_implementation" if is_terra else "sol_advisor",
    }


def _fingerprint(**fields: object) -> str:
    normalized = {key: dict(value) if isinstance(value, Mapping) else value for key, value in fields.items()}
    encoded = dumps(normalized, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(encoded).hexdigest()[:16]
