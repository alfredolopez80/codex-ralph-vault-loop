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

from .active_context import ActiveContext, active_context_from_payload, fast_git_head_for
from .convergent_contracts import (
    ContractError,
    TaskIdentity,
    digest_text,
    new_state,
    validate_state,
)
from .convergent_store import MAX_PLAN_BYTES, ConvergentStore, ConvergentStoreError
from .execution_lease import LeaseError, acquire_execution_lease, assert_lease_stable
from .execution_policy import ExecutionPolicy, assert_policy_compatible, load_execution_policy
from .progress_hook import ProgressLookup, cheap_lookup
from .convergent_reducer import TransitionRequest
from .runtime_attestation import RuntimeAttestation, RuntimeAttestationError, load_runtime_attestation


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
    checkout_head_sha: str


def resolve_authority(payload: Mapping[str, object], *, resolve_git: bool = True) -> AuthorityContext:
    """Resolve the exact plan/store identity for the active worktree."""

    try:
        policy = load_execution_policy()
        active = active_context_from_payload(dict(payload), resolve_git=resolve_git, trust_payload_identity=False)
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
    if resolve_git:
        _git_root, _branch, checkout_head_sha = fast_git_head_for(active.workspace_root)
    else:
        checkout_head_sha = ""
    checkout_head_sha = checkout_head_sha.strip().lower()
    checkout_head_digest = digest_text(checkout_head_sha) if checkout_head_sha else ""
    store = ConvergentStore(lookup.store, policy, checkout_head_digest=checkout_head_digest)
    return AuthorityContext(active, lookup, policy, store, plan_id, plan_version, plan_digest, plan_path, checkout_head_sha)


def load_authoritative_state(payload: Mapping[str, object]) -> tuple[AuthorityContext, dict[str, Any]]:
    """Read and bind the persisted v4 state; caller state is never authority."""

    authority = resolve_authority(payload)
    try:
        attestation = _require_runtime_attestation(authority)
        result = authority.store.read_current(authority.plan_id, authoritative=True)
        if not result.state:
            raise AuthorityError("convergent-state-unavailable")
        state = validate_state(result.state)
        _validate_binding(authority, state, attestation=attestation)
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
            authority = resolve_authority(payload, resolve_git=False)
        except AuthorityError:
            # Shadow is report-only when no approved plan is active.  It must
            # still return a bounded candidate record rather than inventing a
            # store or blocking the legacy prompt path.
            return {
                "plan_id": "",
                "policy_hash": "",
                "boundary_kind": _wire_boundary_kind(boundary.get("boundary_kind")),
                "risk": str(boundary.get("risk") or ""),
                "complexity": int(boundary.get("complexity") or 0),
                "state_available": False,
            }
        return {
            "plan_id": authority.plan_id,
            "policy_hash": authority.policy.policy_hash,
            "boundary_kind": _wire_boundary_kind(boundary.get("boundary_kind")),
            "risk": str(boundary.get("risk") or ""),
            "complexity": int(boundary.get("complexity") or 0),
            "state_available": authority.store.read_current(authority.plan_id).state is not None,
        }
    authority = resolve_authority(payload)
    attestation = _require_runtime_attestation(authority)

    current = authority.store.read_current(authority.plan_id)
    if current.state is not None:
        state = validate_state(current.state)
        _validate_binding(authority, state, attestation=attestation)
        boundary_kind = _wire_boundary_kind(boundary.get("boundary_kind"))
        if boundary_kind == "new_task":
            candidate = _new_epoch_state(authority, payload, prompt, boundary, state)
            evidence = attestation.lease_evidence(
                cwd=str(authority.active.workspace_root),
                branch=authority.active.branch,
                task_epoch=str(candidate["task_epoch"]),
            )
            try:
                lease = acquire_execution_lease(evidence, policy=authority.policy, issued_generation=0)
                result = authority.store.rotate_epoch_and_transition(
                    candidate,
                    TransitionRequest(
                        operation_id="prompt-boundary-" + candidate["task_id"][7:39],
                        transition="BOUNDARY_CLASSIFIED",
                        expected_generation=0,
                        evidence_ids=("prompt-boundary", "epoch-rotation"),
                        actor_role="deterministic-runtime",
                        lease=lease,
                    ),
                )
                return dict(result.state or candidate)
            except (LeaseError, ConvergentStoreError, ContractError, TypeError, ValueError) as exc:
                raise AuthorityError("convergent-new-epoch-cannot-be-committed") from exc
        if boundary_kind in {"material_change", "scope_extension", "user_override"}:
            raise AuthorityError("convergent-amendment-required")
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
        boundary_kind=_wire_boundary_kind(boundary.get("boundary_kind")) or "new_task",
        risk=str(boundary.get("risk") or "low"),
        activation_mode="enforce",
    )
    evidence = attestation.lease_evidence(
        cwd=str(authority.active.workspace_root),
        branch=authority.active.branch,
        task_epoch=task_epoch,
    )
    try:
        lease = acquire_execution_lease(evidence, policy=authority.policy, issued_generation=0)
        result = authority.store.start_and_transition(
            state,
            TransitionRequest(
                operation_id="prompt-boundary-" + state["task_id"][7:39],
                transition="BOUNDARY_CLASSIFIED",
                expected_generation=0,
                evidence_ids=("prompt-boundary",),
                actor_role="deterministic-runtime",
                lease=lease,
            ),
        )
        return dict(result.state or state)
    except (LeaseError, ConvergentStoreError, ContractError, TypeError, ValueError) as exc:
        raise AuthorityError("convergent-boundary-cannot-be-committed") from exc


def _validate_binding(
    authority: AuthorityContext,
    state: Mapping[str, Any],
    *,
    attestation: RuntimeAttestation | None = None,
) -> None:
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
            verified = attestation or _require_runtime_attestation(authority)
            try:
                evidence = verified.lease_evidence(
                    cwd=str(authority.active.workspace_root),
                    branch=authority.active.branch,
                    task_epoch=str(state.get("task_epoch") or ""),
                )
                assert_lease_stable(lease, evidence, policy=authority.policy)
            except LeaseError as exc:
                raise AuthorityError("convergent-lease-attestation-required") from exc


def _require_runtime_attestation(authority: AuthorityContext) -> RuntimeAttestation:
    """Require an independently materialized runtime identity in enforce."""

    if not authority.checkout_head_sha:
        raise AuthorityError("convergent-runtime-attestation-unavailable")
    try:
        return load_runtime_attestation(
            authority.active.workspace_root,
            branch=authority.active.branch,
            head_sha=authority.checkout_head_sha,
            policy=authority.policy,
        )
    except (RuntimeAttestationError, OSError, ValueError, TypeError) as exc:
        raise AuthorityError("convergent-runtime-attestation-unavailable") from exc


def _boundary_epoch(payload: Mapping[str, object]) -> int:
    value = payload.get("boundary_epoch") or payload.get("boundaryEpoch")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 1
    return value


def _wire_boundary_kind(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().replace("-", "_")


def _task_epoch(payload: Mapping[str, object], boundary: Mapping[str, object]) -> str:
    value = payload.get("task_epoch") or payload.get("taskEpoch") or payload.get("task_signature")
    if not isinstance(value, str) or not value.strip():
        value = "epoch-" + str(_boundary_epoch(payload))
    return value.strip()[:180]


def _new_epoch_state(
    authority: AuthorityContext,
    payload: Mapping[str, object],
    prompt: str,
    boundary: Mapping[str, object],
    previous: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a fresh task identity without reusing the prior epoch."""

    previous_epoch = str(previous.get("task_epoch") or "")
    previous_boundary_epoch = int(previous.get("boundary_epoch") or 0)
    requested_epoch = _task_epoch(payload, boundary)
    task_epoch = requested_epoch if requested_epoch and requested_epoch != previous_epoch else f"epoch-{previous_boundary_epoch + 1}"
    boundary_epoch = max(_boundary_epoch(payload), previous_boundary_epoch + 1)
    rank = {"low": 0, "material": 1, "critical": 2}
    previous_risk = str(previous.get("risk") or "low")
    requested_risk = str(boundary.get("risk") or previous_risk)
    risk = requested_risk if rank.get(requested_risk, -1) >= rank.get(previous_risk, 0) else previous_risk
    identity = TaskIdentity.from_values(
        session=authority.active.session_id,
        project=authority.active.project_id,
        worktree=str(authority.active.workspace_root),
        branch=authority.active.branch,
        objective=_objective(payload, prompt),
        boundary_epoch=boundary_epoch,
        sensitivity=str(payload.get("sensitivity") or boundary.get("sensitivity") or "GREEN"),
        plan=authority.plan_id,
        plan_version=authority.plan_version,
        plan_digest=authority.plan_digest,
    )
    return new_state(
        policy=authority.policy,
        plan_id=authority.plan_id,
        plan_version=authority.plan_version,
        plan_digest=authority.plan_digest,
        task_identity=identity,
        goal_id=str(payload.get("goal_id") or "G-BASELINE"),
        task_epoch=task_epoch,
        boundary_epoch=boundary_epoch,
        boundary_kind=_wire_boundary_kind(boundary.get("boundary_kind")) or "new_task",
        risk=risk,
        activation_mode="enforce",
    )


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
    if resolved.stat().st_size > MAX_PLAN_BYTES:
        raise AuthorityError("convergent-plan-provenance-unavailable")
    with resolved.open("rb") as handle:
        raw = handle.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES:
        raise AuthorityError("convergent-plan-provenance-unavailable")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


__all__ = ["AuthorityContext", "AuthorityError", "ensure_prompt_boundary", "load_authoritative_state", "resolve_authority"]
