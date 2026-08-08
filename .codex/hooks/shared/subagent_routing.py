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

from .agent_budget import (
    MAX_DEPTH,
    MAX_PACKET_BYTES,
    MAX_TASK_ADVISORS,
    MAX_TASK_JOBS,
    MAX_THREADS,
)
from .runtime_profile import classify_model

POLICY_VERSION = "subagent-routing-v2"
LUNA_MODEL = "gpt-5.6-luna"
TERRA_MODEL = "gpt-5.6-terra"
SOL_MODEL = "gpt-5.6-sol"
LUNA_DEFAULT_EFFORT = "max"
TERRA_EFFORT = "high"
SOL_EFFORTS = {8: "high", 9: "xhigh", 10: "max"}
EFFORT_RANK = {"high": 1, "xhigh": 2, "max": 3}
SUPPORTED_ROUTES = frozenset({"terra-implementation", "sol-advisor", "sol-active-analysis"})
DEEP_INTENTS = frozenset(
    {
        "architecture",
        "claim-adjudication",
        "debugging",
        "migration",
        "security",
        "spec-review",
        "high-impact-review",
    }
)


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
    # Gate evidence is safety-critical.  A caller must prove it explicitly;
    # omission cannot authorize active Sol analysis or an effort downgrade.
    hard_gates_pass: bool = False
    # Delegation is opt-in even in high-complexity bands.  These fields are
    # structured evidence supplied by the intake layer, never inferred from
    # prompt length or transcript heuristics.
    independent_block: bool = False
    independent_block_count: int = 0
    critical_review: bool = False
    failure_fingerprints: tuple[str, ...] = ()


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
    override_rejections: Mapping[str, object]
    override_expiry: int | None
    budget_remaining: int
    decision_fingerprint: str
    reason_code: str
    max_threads: int
    max_depth: int
    max_task_jobs: int
    max_task_advisors: int
    packet_budget_bytes: int


def resolve_subagent_routing(request: RoutingRequest) -> RoutingDecision:
    """Resolve a bounded subagent recommendation without mutating request state."""
    raw = _complexity(request.raw_complexity)
    intent = _intent(request.intent)
    impact = _impact(request.impact_class)
    sensitivity = request.sensitivity.strip().upper()
    executor, executor_source = _executor_defaults(request)
    effective = 4 if raw <= 3 and impact == "material" else raw
    active_ok, active_reason = _active_analysis_status(request, effective, sensitivity)
    override, scope, requested, expiry, override_error, override_rejections = _selected_override(request)

    executor_family = classify_model(executor.model)
    route, model, mode, effort, reason = _base_route(
        raw,
        effective,
        intent,
        sensitivity,
        executor_family=executor_family,
        independent_block=request.independent_block,
        critical_review=request.critical_review,
        failure_fingerprints=request.failure_fingerprints,
    )
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
            override_rejections = _record_override_rejection(
                override_rejections,
                scope=scope,
                requested=requested,
                expiry=override.expires_at,
                reason=override_error,
            )
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
            if override is not None:
                override_rejections = _record_override_rejection(
                    override_rejections,
                    scope=scope,
                    requested=requested,
                    expiry=override.expires_at,
                    reason=override_error,
                )

    # Explicit overrides are still subordinate to the phase policy.  They may
    # choose an eligible lane, but cannot turn trivial work into a child spawn,
    # create a worker without an independently measurable block, or make Sol
    # supervise itself outside a critical review phase.
    if route != "none" and raw <= 3:
        route, model, mode, effort = "none", None, "none", None
        reason = "direct-1-3"
        effective_override = _frozen_map()
        override_error = override_error or "complexity-band-does-not-delegate"
    elif route == "terra-implementation" and not request.independent_block:
        route, model, mode, effort = "none", None, "none", None
        reason = "independent-block-required"
        effective_override = _frozen_map()
        override_error = override_error or "independent-block-required"
    elif route in {"sol-advisor", "sol-active-analysis"} and executor_family == "sol" and not request.critical_review:
        route, model, mode, effort = "none", None, "none", None
        reason = "sol-self-supervision-suppressed"
        effective_override = _frozen_map()
        override_error = override_error or "sol-self-supervision-suppressed"

    if route != "none" and not request.capabilities.spawn_model_effort:
        route, model, mode, effort = "none", None, "none", None
        reason = "platform-spawn-model-effort-unavailable"
        effective_override = _frozen_map()
        override_error = override_error or "platform-spawn-model-effort-unavailable"
        if override is not None and override_error:
            override_rejections = _record_override_rejection(
                override_rejections,
                scope=scope,
                requested=requested,
                expiry=override.expires_at,
                reason=override_error,
            )
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
        override_error=override_error,
        override_rejections=override_rejections,
        override_expiry=expiry,
        capabilities=request.capabilities,
        explicit_budget=request.budget.explicit_class,
        independent_block=request.independent_block,
        independent_block_count=request.independent_block_count,
        critical_review=request.critical_review,
        failure_fingerprints=tuple(request.failure_fingerprints),
        # Consultation availability and explanatory status are live
        # lifecycle facts, not part of the decision identity. The pre-tool
        # guard rechecks the current budget immediately before a Sol spawn,
        # so consuming a consultation must not manufacture a new task
        # fingerprint.
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
        override_rejections=_frozen_map(override_rejections),
        override_expiry=expiry,
        budget_remaining=max(0, request.budget.remaining),
        decision_fingerprint=fingerprint,
        reason_code=reason,
        max_threads=MAX_THREADS,
        max_depth=MAX_DEPTH,
        max_task_jobs=MAX_TASK_JOBS,
        max_task_advisors=MAX_TASK_ADVISORS,
        packet_budget_bytes=MAX_PACKET_BYTES,
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


def _base_route(
    raw: int,
    effective: int,
    intent: str,
    sensitivity: str,
    *,
    executor_family: str,
    independent_block: bool,
    critical_review: bool,
    failure_fingerprints: tuple[str, ...],
) -> tuple[str, str | None, str, str | None, str]:
    if sensitivity == "RED":
        return "none", None, "none", None, "red-local-only"
    if raw <= 3:
        return "none", None, "none", None, "routine-luna-only"
    distinct_failures = {fingerprint for fingerprint in failure_fingerprints if fingerprint}
    if distinct_failures and len(distinct_failures) < 2:
        return "none", None, "none", None, "inspect-first-failure-locally"
    # 4-6 remains direct unless the caller proves a measurable independent
    # block.  This avoids routine fan-out while retaining an explicit worker
    # escape hatch for work that can be independently verified.
    if effective in range(4, 7):
        if independent_block and intent == "implementation":
            return "terra-implementation", TERRA_MODEL, "implementation", TERRA_EFFORT, "independent-worker-4-6"
        return "none", None, "none", None, "direct-4-6"
    if effective in range(7, 9):
        if independent_block and intent == "implementation":
            return "terra-implementation", TERRA_MODEL, "implementation", TERRA_EFFORT, "independent-worker-7-8"
        if executor_family == "sol" and not critical_review:
            return "none", None, "none", None, "sol-self-supervision-suppressed"
        if intent in DEEP_INTENTS:
            return "sol-advisor", SOL_MODEL, "advisor", SOL_EFFORTS[8], "sol-advisor-7-8"
        return "none", None, "none", None, "direct-7-8"
    if effective >= 9 and independent_block:
        return "terra-implementation", TERRA_MODEL, "implementation", TERRA_EFFORT, "independent-worker-9-10"
    if effective >= 9 and intent in DEEP_INTENTS:
        if executor_family == "sol" and not critical_review:
            return "none", None, "none", None, "sol-self-supervision-suppressed"
        effort = SOL_EFFORTS[min(effective, 10)]
        return "sol-advisor", SOL_MODEL, "advisor", effort, f"sol-advisor-{effective}"
    return "none", None, "none", None, "intent-does-not-qualify-for-automatic-subagent"


def _record_override_rejection(
    existing: Mapping[str, object],
    *,
    scope: str,
    requested: Mapping[str, object],
    expiry: int | None,
    reason: str,
) -> Mapping[str, object]:
    merged = dict(existing)
    merged[scope] = {
        "requested": dict(requested),
        "expires_at": expiry,
        "reason": reason,
    }
    return merged


def _selected_override(
    request: RoutingRequest,
) -> tuple[
    SubagentOverride | None,
    str,
    Mapping[str, object],
    int | None,
    str | None,
    Mapping[str, object],
]:
    def requested_values(candidate: SubagentOverride) -> Mapping[str, object]:
        return _frozen_map(
            {
                key: value
                for key, value in {
                    "model": candidate.model,
                    "reasoning_effort": candidate.reasoning_effort,
                    "route": candidate.route,
                }.items()
                if value is not None
            }
        )

    task = request.task_override
    if task is not None:
        task_requested = requested_values(task)
        task_expired = task.expires_at is not None and task.expires_at <= request.current_epoch
        if not task_expired:
            return task, "task", task_requested, task.expires_at, None, _frozen_map()

        session = request.session_override
        rejected = _record_override_rejection(
            {}, scope="task", requested=task_requested, expiry=task.expires_at, reason="override-expired"
        )
        if session is not None:
            session_expired = session.expires_at is not None and session.expires_at <= request.current_epoch
            if not session_expired:
                # Preserve the expired task fact while applying the valid
                # lower-precedence session policy.
                return session, "session", requested_values(session), session.expires_at, None, rejected
            rejected = _record_override_rejection(
                rejected,
                scope="session",
                requested=requested_values(session),
                expiry=session.expires_at,
                reason="override-expired",
            )
        return None, "task", task_requested, task.expires_at, "override-expired", rejected

    session = request.session_override
    if session is None:
        return None, "none", _frozen_map(), None, None, _frozen_map()
    requested = requested_values(session)
    if session.expires_at is not None and session.expires_at <= request.current_epoch:
        rejected = _record_override_rejection(
            {}, scope="session", requested=requested, expiry=session.expires_at, reason="override-expired"
        )
        return None, "session", requested, session.expires_at, "override-expired", rejected
    return session, "session", requested, session.expires_at, None, _frozen_map()


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
    if not request.hard_gates_pass:
        return False, "active-analysis-requires-hard-gates"
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


def session_routing_context() -> str:
    """Return a bounded, non-authoritative reminder for new sessions."""
    return (
        f"Model routing policy {POLICY_VERSION} (non-authoritative reminder): "
        f"configured executor remains {LUNA_MODEL}/{LUNA_DEFAULT_EFFORT}. "
        f"max_threads={MAX_THREADS}, max_depth={MAX_DEPTH}; "
        f"complexity 1-3 stays direct; 4-6 stays direct unless an independent measurable block is proven; "
        f"7-8 uses at most one bounded {SOL_MODEL}/{SOL_EFFORTS[8]} advisor only for high-value intents; "
        f"9 {SOL_MODEL}/{SOL_EFFORTS[9]} advisor; "
        f"10 {SOL_MODEL}/{SOL_EFFORTS[10]} advisor. "
        f"At most {MAX_TASK_JOBS} independent jobs per task and no automatic fan-out. "
        "SOL never self-supervises outside an explicitly critical independent review; RED stays local. "
        "Codex main owns decisions; this reminder never switches the current model or carries history."
    )
