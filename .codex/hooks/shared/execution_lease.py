"""Stable, non-fallback execution lease for the v4 implementation owner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .convergent_contracts import ExecutionLease, digest_text, digest_value
from .execution_policy import (
    AUTHORITY_ROLE,
    IMPLEMENTATION_ROLE,
    REQUIRED_IMPLEMENTATION_MODEL,
    REQUIRED_REASONING_EFFORT,
    ExecutionPolicy,
)


class LeaseError(ValueError):
    """Raised when the runtime cannot prove the exact SOL/max owner."""


@dataclass(frozen=True)
class LeaseEvidence:
    model: str
    reasoning_effort: str
    tools: tuple[str, ...]
    cwd: str
    branch: str
    task_epoch: str
    owner_role: str = IMPLEMENTATION_ROLE
    authority_role: str = AUTHORITY_ROLE
    source: str = "payload"
    fallback_requested: bool = False


@dataclass(frozen=True)
class DelegationEvidence:
    automatic: bool
    active_children: int
    total_threads: int
    depth: int
    nested: bool
    independent_block: bool
    measurable_success: bool
    non_overlapping_write_scope: bool


def evidence_from_payload(
    payload: Mapping[str, object],
    *,
    task_epoch: str,
    verified_source: str = "payload",
) -> LeaseEvidence:
    """Shape platform metadata without trusting a source claim inside payload."""

    model = _explicit_string(payload, ("model", "model_name", "modelName"))
    effort = _explicit_string(payload, ("model_reasoning_effort", "reasoning_effort", "reasoningEffort"))
    tools = _tools(payload)
    cwd = _explicit_string(payload, ("cwd", "workdir", "workspace_root", "workspaceRoot"))
    branch = _explicit_string(payload, ("branch", "git_branch", "gitBranch"))
    owner = _explicit_string(payload, ("implementation_owner", "implementationOwner", "owner_role")) or IMPLEMENTATION_ROLE
    authority = _explicit_string(payload, ("authority_role", "authorityRole")) or AUTHORITY_ROLE
    fallback = any(
        bool(payload.get(key))
        for key in ("fallback", "fallback_model", "fallbackModel", "allow_fallback", "allowFallback")
    )
    return LeaseEvidence(
        model=model,
        reasoning_effort=effort,
        tools=tools,
        cwd=cwd,
        branch=branch,
        task_epoch=task_epoch,
        owner_role=owner,
        authority_role=authority,
        source=verified_source,
        fallback_requested=fallback,
    )


def acquire_execution_lease(
    evidence: LeaseEvidence,
    *,
    policy: ExecutionPolicy,
    issued_generation: int,
) -> ExecutionLease:
    validate_lease_evidence(evidence, policy=policy)
    if isinstance(issued_generation, bool) or not isinstance(issued_generation, int) or issued_generation < 0:
        raise LeaseError("lease generation must be nonnegative")
    material = {
        "model": evidence.model,
        "effort": evidence.reasoning_effort,
        "toolset_fingerprint": digest_value(sorted(evidence.tools)),
        "cwd_fingerprint": digest_text(evidence.cwd),
        "branch_fingerprint": digest_text(evidence.branch),
        "task_epoch_fingerprint": digest_text(evidence.task_epoch),
        "implementation_owner": evidence.owner_role,
        "authority_owner": evidence.authority_role,
        "issued_generation": issued_generation,
    }
    lease_id = "lease-" + digest_value(material).split(":", 1)[1][:32]
    return ExecutionLease(
        lease_id=lease_id,
        implementation_owner=evidence.owner_role,
        authority_owner=evidence.authority_role,
        model=evidence.model,
        effort=evidence.reasoning_effort,
        toolset_fingerprint=material["toolset_fingerprint"],
        cwd_fingerprint=material["cwd_fingerprint"],
        branch_fingerprint=material["branch_fingerprint"],
        task_epoch_fingerprint=material["task_epoch_fingerprint"],
        issued_generation=issued_generation,
    )


def validate_lease_evidence(evidence: LeaseEvidence, *, policy: ExecutionPolicy) -> None:
    if evidence.fallback_requested:
        raise LeaseError("automatic model fallback is forbidden")
    if evidence.model != REQUIRED_IMPLEMENTATION_MODEL:
        raise LeaseError("implementation owner must be real gpt-5.6-sol")
    if evidence.reasoning_effort != REQUIRED_REASONING_EFFORT:
        raise LeaseError("implementation owner reasoning effort must be max")
    if evidence.owner_role != IMPLEMENTATION_ROLE:
        raise LeaseError("read-only advisor or alternate owner cannot hold the execution lease")
    if evidence.authority_role != AUTHORITY_ROLE:
        raise LeaseError("Codex main must remain the authority owner")
    if evidence.source not in {"platform", "verified-runtime", "manual-approval"}:
        raise LeaseError("execution identity source is not authorized")
    if not evidence.tools or any(not tool or len(tool) > 160 for tool in evidence.tools):
        raise LeaseError("execution lease requires a bounded non-empty toolset")
    if len(set(evidence.tools)) != len(evidence.tools):
        raise LeaseError("execution toolset must be canonical and duplicate-free")
    if (
        not evidence.cwd
        or len(evidence.cwd.encode("utf-8")) > 4_096
        or not evidence.branch
        or len(evidence.branch) > 180
        or not evidence.task_epoch
        or len(evidence.task_epoch) > 180
    ):
        raise LeaseError("execution lease requires stable cwd, branch, and task epoch")
    model_policy = policy.section("model_selection")
    if not all(
        model_policy[key]
        for key in ("keep_model_stable", "keep_reasoning_effort_stable", "keep_toolset_stable", "keep_cwd_stable")
    ):
        raise LeaseError("v4 stability requirements are not active")


def assert_lease_stable(
    lease: Mapping[str, Any],
    evidence: LeaseEvidence,
    *,
    policy: ExecutionPolicy,
) -> None:
    validate_lease_evidence(evidence, policy=policy)
    if lease.get("active") is not True:
        raise LeaseError("execution lease is not active")
    expected = {
        "model": evidence.model,
        "effort": evidence.reasoning_effort,
        "toolset_fingerprint": digest_value(sorted(evidence.tools)),
        "cwd_fingerprint": digest_text(evidence.cwd),
        "branch_fingerprint": digest_text(evidence.branch),
        "task_epoch_fingerprint": digest_text(evidence.task_epoch),
        "implementation_owner": evidence.owner_role,
        "authority_owner": evidence.authority_role,
    }
    for key, value in expected.items():
        if lease.get(key) != value:
            raise LeaseError(f"execution lease drift: {key}")


def validate_delegation_evidence(evidence: DelegationEvidence, *, policy: ExecutionPolicy) -> None:
    """Enforce the finite v4 delegation envelope without starting a child."""

    delegation = policy.section("delegation")
    for label, value in (
        ("active_children", evidence.active_children),
        ("total_threads", evidence.total_threads),
        ("depth", evidence.depth),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LeaseError(f"delegation {label} must be nonnegative")
    if evidence.automatic or int(delegation["automatic_subagents"]) != 0:
        raise LeaseError("automatic delegation is forbidden")
    if evidence.total_threads < 1 or evidence.depth < 1:
        raise LeaseError("delegation evidence must include the root thread and child depth")
    if evidence.active_children >= int(delegation["max_active_children"]):
        raise LeaseError("active child budget is exhausted")
    if evidence.total_threads >= int(delegation["hard_max_threads"]):
        raise LeaseError("hard thread budget is exhausted")
    if evidence.depth > int(delegation["max_depth"]):
        raise LeaseError("delegation depth exceeds policy")
    if evidence.nested or bool(delegation["nested_delegation"]):
        raise LeaseError("nested delegation is forbidden")
    required = {
        "independent block": evidence.independent_block,
        "measurable success": evidence.measurable_success,
        "non-overlapping write scope": evidence.non_overlapping_write_scope,
    }
    missing = [label for label, present in required.items() if not present]
    if missing:
        raise LeaseError("delegation lacks " + ", ".join(missing))


def _explicit_string(payload: Mapping[str, object], keys: Sequence[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for parent in ("runtime", "metadata", "agent"):
        nested = payload.get(parent)
        if isinstance(nested, Mapping):
            for key in keys:
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _tools(payload: Mapping[str, object]) -> tuple[str, ...]:
    candidates: list[Mapping[str, object]] = [payload]
    for parent in ("runtime", "metadata", "agent"):
        nested = payload.get(parent)
        if isinstance(nested, Mapping):
            candidates.append(nested)
    for candidate in candidates:
        for key in ("available_tools", "availableTools", "tools", "toolset"):
            value = candidate.get(key)
            if isinstance(value, Mapping):
                return tuple(sorted(str(item).strip() for item in value if str(item).strip()))
            if isinstance(value, (list, tuple)):
                names: list[str] = []
                for item in value:
                    if isinstance(item, str):
                        name = item.strip()
                    elif isinstance(item, Mapping):
                        name = str(item.get("name") or item.get("tool_name") or "").strip()
                    else:
                        name = ""
                    if name:
                        names.append(name)
                return tuple(sorted(names))
    return ()


__all__ = [
    "DelegationEvidence",
    "LeaseError",
    "LeaseEvidence",
    "acquire_execution_lease",
    "assert_lease_stable",
    "evidence_from_payload",
    "validate_delegation_evidence",
    "validate_lease_evidence",
]
