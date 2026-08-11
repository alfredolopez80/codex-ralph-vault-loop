"""Canonical authority boundary for live v4 lifecycle hooks.

The pure contracts remain useful in isolation, but an enforce-mode decision
must be bound to the current worktree and the canonical implementation store.
This adapter resolves those values independently of the caller's optional
``convergence_state`` hint and exposes only a validated state snapshot to the
pure Stop reducer.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import stat
from typing import Any, Mapping
from pathlib import Path

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
from .execution_policy import ExecutionPolicy, assert_policy_compatible, load_execution_policy
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
    plan_version: int
    plan_digest: str
    plan_path: str


def resolve_authority(payload: Mapping[str, object]) -> AuthorityContext:
    """Resolve the exact plan/store identity for the active worktree."""

    try:
        policy = load_execution_policy()
        active = active_context_from_payload(dict(payload), resolve_git=True, trust_payload_identity=False)
        supplied_branch = payload.get("branch") or payload.get("git_branch")
        supplied_sha = payload.get("sha") or payload.get("git_sha")
        if isinstance(supplied_branch, str) and supplied_branch.strip() and supplied_branch.strip() != active.branch:
            raise AuthorityError("convergent-branch-mismatch")
        if isinstance(supplied_sha, str) and supplied_sha.strip() and not _sha_matches(supplied_sha.strip(), active.sha):
            raise AuthorityError("convergent-head-mismatch")
        lookup = cheap_lookup(active, payload)
    except AuthorityError:
        raise
    except Exception as exc:  # typed below at the public boundary
        raise AuthorityError("convergent-authority-unavailable") from exc
    if not lookup.available or lookup.store is None or lookup.identity is None:
        raise AuthorityError("convergent-state-unavailable")
    store = ConvergentStore(lookup.store, policy)
    plan_id = lookup.identity.plan_id
    plan_path = lookup.identity.plan_path
    try:
        registered = store.progress.read_state(plan_id) or {}
        plan_path = str(plan_path or registered.get("plan_path") or "")
        plan_version = int(registered.get("plan_version") or 1)
        plan_digest = _plan_digest(store.progress.paths.primary_root, plan_path)
    except (OSError, TypeError, ValueError, ConvergentStoreError) as exc:
        raise AuthorityError("convergent-plan-provenance-unavailable") from exc
    return AuthorityContext(active, lookup, policy, store, plan_id, plan_version, plan_digest, plan_path)


def load_authoritative_state(payload: Mapping[str, object]) -> tuple[AuthorityContext, dict[str, Any]]:
    """Read and bind the persisted v4 state; caller state is never authority."""

    authority = resolve_authority(payload)
    try:
        result = authority.store.read_current(authority.plan_id, authoritative=True)
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
        boundary_kind = str(boundary.get("boundary_kind") or "")
        if boundary_kind in {"new-task", "material-change", "scope-extension", "user-override"}:
            # Epoch rotation is a separate canonical operation. Reusing the
            # immutable execution namespace would attribute new work to a
            # closed/active task, so enforce fails closed until that archive
            # operation is explicitly available.
            raise AuthorityError("convergent-new-epoch-required")
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
        plan_version=authority.plan_version,
        plan_digest=authority.plan_digest,
    )
    goal_id = str(payload.get("goal_id") or "G-BASELINE")
    state = new_state(
        policy=authority.policy,
        plan_id=authority.plan_id,
        plan_version=authority.plan_version,
        plan_digest=authority.plan_digest,
        task_identity=identity,
        goal_id=goal_id,
        task_epoch=task_epoch,
        boundary_epoch=epoch,
        boundary_kind=str(boundary.get("boundary_kind") or "new_task"),
        risk=str(boundary.get("risk") or "low"),
        activation_mode="enforce",
    )
    evidence = evidence_from_payload(
        payload,
        task_epoch=task_epoch,
        # The caller cannot promote its own metadata to a platform
        # attestation.  A future trusted runtime adapter must call
        # ``acquire_execution_lease`` directly with verified evidence.
        verified_source="payload",
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
    if (
        state.get("plan_id") != authority.plan_id
        or state.get("plan_version") != authority.plan_version
        or state.get("plan_digest") != authority.plan_digest
    ):
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
    # A Codex session is writer provenance, not the task's authority boundary.
    # Continuations may resume in a new CLI/App session while retaining the
    # same plan, task epoch, worktree, branch, and lease.  The immutable
    # session hash remains in TaskIdentity for audit provenance; it must not
    # make a valid cross-session continuation unrecoverable.
    lease = state.get("execution_lease")
    if state.get("phase") not in {"prompt_gate", "blocked", "user_decision", "close"} and not isinstance(lease, Mapping):
        raise AuthorityError("convergent-lease-missing")
    if isinstance(lease, Mapping):
        if lease.get("branch_fingerprint") != digest_text(authority.active.branch):
            raise AuthorityError("convergent-lease-branch-mismatch")
        if lease.get("cwd_fingerprint") != digest_text(str(authority.active.workspace_root)):
            raise AuthorityError("convergent-lease-cwd-mismatch")
        # A persisted lease is not self-authenticating.  The current hook
        # payload is not a trusted platform attestation, so an enforce-time
        # load must fail closed until such an adapter supplies verified
        # runtime evidence.  This prevents stale model/toolset/epoch claims
        # from authorizing a material or terminal transition.
        if state.get("phase") not in {"prompt_gate", "blocked", "user_decision", "close"}:
            raise AuthorityError("convergent-lease-attestation-required")


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


def _sha_matches(supplied: str, actual: str) -> bool:
    if not supplied or not actual or any(character not in "0123456789abcdefABCDEF" for character in supplied + actual):
        return False
    supplied = supplied.lower()
    actual = actual.lower()
    if len(supplied) < 7 or len(supplied) > 40 or len(actual) < 7 or len(actual) > 40:
        return False
    return supplied == actual or supplied.startswith(actual) or actual.startswith(supplied)


def _plan_digest(root: Path, relative_path: str) -> str:
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        raise AuthorityError("convergent-plan-provenance-unavailable")
    candidate = root / relative
    info = candidate.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AuthorityError("convergent-plan-provenance-unavailable")
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    resolved.relative_to(resolved_root)
    return "sha256:" + hashlib.sha256(resolved.read_bytes()).hexdigest()


__all__ = ["AuthorityContext", "AuthorityError", "ensure_prompt_boundary", "load_authoritative_state", "resolve_authority"]
