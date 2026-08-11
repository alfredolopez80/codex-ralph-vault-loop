"""Canonical authority boundary for live v4 lifecycle hooks.

The pure contracts remain useful in isolation, but an enforce-mode decision
must be bound to the current worktree and the canonical implementation store.
This adapter resolves those values independently of the caller's optional
``convergence_state`` hint and exposes only a validated state snapshot to the
pure Stop reducer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .active_context import ActiveContext, active_context_from_payload
from .convergent_contracts import (
    ContractError,
    TaskIdentity,
    digest_text,
    new_state,
    validate_state,
)
from .convergent_store import ConvergentStore, ConvergentStoreError
from .execution_lease import LeaseError, acquire_execution_lease, evidence_from_payload
from .execution_policy import (
    ACTIVATION_PLAN_DIGEST,
    ACTIVATION_PLAN_ID,
    ExecutionPolicy,
    assert_policy_compatible,
    load_execution_policy,
)
from .progress_hook import ProgressLookup, cheap_lookup
from .convergent_reducer import TransitionRequest


class AuthorityError(RuntimeError):
    """Raised when the live runtime cannot prove v4 authority."""


@dataclass(frozen=True)
class AuthorityContext:
    active: ActiveContext
    lookup: ProgressLookup
    policy: ExecutionPolicy
    store: ConvergentStore
    plan_id: str


def resolve_authority(payload: Mapping[str, object]) -> AuthorityContext:
    """Resolve the exact plan/store identity for the active worktree."""

    try:
        policy = load_execution_policy()
        active = active_context_from_payload(dict(payload), resolve_git=True)
        lookup = cheap_lookup(active, payload)
    except Exception as exc:  # typed below at the public boundary
        raise AuthorityError("convergent-authority-unavailable") from exc
    if not lookup.available or lookup.store is None or lookup.identity is None:
        raise AuthorityError("convergent-state-unavailable")
    if lookup.identity.plan_id != ACTIVATION_PLAN_ID:
        raise AuthorityError("convergent-plan-identity-mismatch")
    store = ConvergentStore(lookup.store, policy)
    return AuthorityContext(active, lookup, policy, store, lookup.identity.plan_id)


def load_authoritative_state(payload: Mapping[str, object]) -> tuple[AuthorityContext, dict[str, Any]]:
    """Read and bind the persisted v4 state; caller state is never authority."""

    authority = resolve_authority(payload)
    try:
        result = authority.store.read_current(authority.plan_id)
        if not result.state:
            raise AuthorityError("convergent-state-unavailable")
        state = validate_state(result.state)
        _validate_binding(authority, state)
        return authority, state
    except AuthorityError:
        raise
    except (ContractError, ConvergentStoreError, OSError, TypeError, ValueError) as exc:
        raise AuthorityError("convergent-state-invalid") from exc


def ensure_prompt_boundary(
    payload: Mapping[str, object],
    *,
    prompt: str,
    boundary: Mapping[str, object],
    mode: str,
) -> dict[str, Any] | None:
    """Bind a new enforce-mode Prompt Boundary to the canonical store.

    Shadow mode evaluates the same authority inputs but does not publish a
    business state transition.  This preserves the rollout boundary while
    making the real enforce path use the same state/lease contract.
    """

    if mode == "off":
        return None
    if mode == "shadow":
        try:
            authority = resolve_authority(payload)
        except AuthorityError:
            # Shadow is report-only when no approved plan is active.  It must
            # still return a bounded candidate record rather than inventing a
            # store or blocking the legacy prompt path.
            return {
                "plan_id": "",
                "policy_hash": "",
                "boundary_kind": str(boundary.get("boundary_kind") or ""),
                "risk": str(boundary.get("risk") or ""),
                "complexity": int(boundary.get("complexity") or 0),
                "state_available": False,
            }
        return {
            "plan_id": authority.plan_id,
            "policy_hash": authority.policy.policy_hash,
            "boundary_kind": str(boundary.get("boundary_kind") or ""),
            "risk": str(boundary.get("risk") or ""),
            "complexity": int(boundary.get("complexity") or 0),
            "state_available": authority.store.read_current(authority.plan_id).state is not None,
        }
    authority = resolve_authority(payload)

    current = authority.store.read_current(authority.plan_id)
    if current.state is not None:
        state = validate_state(current.state)
        _validate_binding(authority, state)
        return state

    task_epoch = _task_epoch(payload, boundary)
    epoch = _boundary_epoch(payload)
    identity = TaskIdentity.from_values(
        session=authority.active.session_id,
        project=authority.active.project_id,
        worktree=str(authority.active.workspace_root),
        branch=authority.active.branch,
        objective=_objective(payload, prompt),
        boundary_epoch=epoch,
        sensitivity=str(payload.get("sensitivity") or boundary.get("sensitivity") or "GREEN"),
        plan=authority.plan_id,
        plan_version=1,
        plan_digest=ACTIVATION_PLAN_DIGEST,
    )
    goal_id = str(payload.get("goal_id") or "G-BASELINE")
    state = new_state(
        policy=authority.policy,
        plan_id=authority.plan_id,
        plan_version=1,
        plan_digest=ACTIVATION_PLAN_DIGEST,
        task_identity=identity,
        goal_id=goal_id,
        task_epoch=task_epoch,
        boundary_epoch=epoch,
        boundary_kind=str(boundary.get("boundary_kind") or "new_task"),
        activation_mode="enforce",
    )
    evidence = evidence_from_payload(
        payload,
        task_epoch=task_epoch,
        verified_source=str(payload.get("lease_source") or payload.get("leaseSource") or "payload"),
    )
    try:
        lease = acquire_execution_lease(evidence, policy=authority.policy, issued_generation=0)
        result = authority.store.start(state)
        transition = authority.store.transition(
            authority.plan_id,
            TransitionRequest(
                operation_id="prompt-boundary-" + state["task_id"][7:39],
                transition="BOUNDARY_CLASSIFIED",
                expected_generation=0,
                evidence_ids=("prompt-boundary",),
                actor_role="deterministic-runtime",
                lease=lease,
            ),
        )
        return dict(transition.state or result.state or state)
    except (LeaseError, ConvergentStoreError, ContractError, TypeError, ValueError) as exc:
        raise AuthorityError("convergent-boundary-cannot-be-committed") from exc


def _validate_binding(authority: AuthorityContext, state: Mapping[str, Any]) -> None:
    if state.get("plan_id") != authority.plan_id or state.get("plan_digest") != ACTIVATION_PLAN_DIGEST:
        raise AuthorityError("convergent-plan-binding-mismatch")
    assert_policy_compatible(state.get("policy_hash"), authority.policy)
    identity = state.get("task_identity")
    if not isinstance(identity, Mapping):
        raise AuthorityError("convergent-task-identity-missing")
    if identity.get("branch") != authority.active.branch:
        raise AuthorityError("convergent-branch-mismatch")
    if identity.get("worktree_id") != digest_text(str(authority.active.workspace_root)):
        raise AuthorityError("convergent-worktree-mismatch")
    if identity.get("project_id") != digest_text(authority.active.project_id):
        raise AuthorityError("convergent-project-mismatch")
    if identity.get("session_id") != digest_text(authority.active.session_id):
        raise AuthorityError("convergent-session-mismatch")
    lease = state.get("execution_lease")
    if state.get("phase") not in {"prompt_gate", "blocked", "user_decision"} and not isinstance(lease, Mapping):
        raise AuthorityError("convergent-lease-missing")
    if isinstance(lease, Mapping):
        if lease.get("branch_fingerprint") != digest_text(authority.active.branch):
            raise AuthorityError("convergent-lease-branch-mismatch")
        if lease.get("cwd_fingerprint") != digest_text(str(authority.active.workspace_root)):
            raise AuthorityError("convergent-lease-cwd-mismatch")


def _boundary_epoch(payload: Mapping[str, object]) -> int:
    value = payload.get("boundary_epoch") or payload.get("boundaryEpoch")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 1
    return value


def _task_epoch(payload: Mapping[str, object], boundary: Mapping[str, object]) -> str:
    value = payload.get("task_epoch") or payload.get("taskEpoch") or payload.get("task_signature")
    if not isinstance(value, str) or not value.strip():
        value = "epoch-" + str(_boundary_epoch(payload))
    return value.strip()[:180]


def _objective(payload: Mapping[str, object], prompt: str) -> str:
    for key in ("objective", "task", "task_signature", "taskSignature"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:2_000]
    return prompt[:2_000]


__all__ = ["AuthorityContext", "AuthorityError", "ensure_prompt_boundary", "load_authoritative_state", "resolve_authority"]
