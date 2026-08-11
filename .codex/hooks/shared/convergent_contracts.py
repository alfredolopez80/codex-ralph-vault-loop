"""Closed schemas for Ralph Convergent Execution v4 control state.

The supplied design fixes the control-state wire schema at version 3.  Policy
version 4 and the existing implementation-progress schema are independent.
Only content-free hashes, identifiers, counters, and bounded enums are
representable here; prompts, logs, memory bodies, and reviewer prose are not.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Final, Mapping, Sequence

from .execution_policy import (
    AUTHORITY_ROLE,
    IMPLEMENTATION_ROLE,
    POLICY_SPEC,
    POLICY_VERSION,
    REQUIRED_IMPLEMENTATION_MODEL,
    REQUIRED_REASONING_EFFORT,
    ExecutionPolicy,
)
from .implementation_store.schema import FutureSchemaError
from .redaction import is_red


STATE_SCHEMA_VERSION: Final[int] = 3
EVENT_SCHEMA_VERSION: Final[int] = 3
MAX_STATE_BYTES: Final[int] = 256 * 1024
MAX_EVENT_BYTES: Final[int] = 32 * 1024
MAX_OBLIGATIONS: Final[int] = 128
MAX_EVIDENCE_IDS: Final[int] = 64
SHA256_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,179}$")

BOUNDARY_KINDS: Final[frozenset[str]] = frozenset(
    {"new_task", "continuation", "clarification", "scope_extension", "material_change", "status_only", "user_override"}
)
PHASES: Final[tuple[str, ...]] = (
    "prompt_gate",
    "analyze",
    "design_ready",
    "approved",
    "implement",
    "verify",
    "review",
    "finding_triage",
    "mitigate",
    "final_audit",
    "anti_rationalization",
    "stop",
    "close",
    "blocked",
    "user_decision",
)
STATUSES: Final[frozenset[str]] = frozenset({"active", "verifying", "closed", "blocked", "user-decision"})
ACTIVATION_MODES: Final[frozenset[str]] = frozenset({"off", "enforce"})
ACTOR_ROLES: Final[frozenset[str]] = frozenset({AUTHORITY_ROLE, IMPLEMENTATION_ROLE, "deterministic-runtime", "reviewer"})
TRANSITIONS: Final[frozenset[str]] = frozenset(
    {
        "BOUNDARY_CLASSIFIED",
        "ARISTOTLE_RECORDED",
        "ADVANCE",
        "AMEND",
        "EVIDENCE_RECORDED",
        "POST_TOOL_RESULT_RECORDED",
        "TRANSIENT_RERUN",
        "REPAIR",
        "REOPEN",
        "REVIEW_RECORDED",
        "FINDINGS_TRIAGED",
        "FINAL_AUDIT_RECORDED",
        "STOP_CONTINUATION",
        "BLOCK",
        "USER_DECISION",
        "CLOSE",
    }
)
TASK_HASH_FIELDS: Final[tuple[str, ...]] = (
    "session_hash",
    "project_hash",
    "worktree_hash",
    "branch_hash",
    "objective_hash",
    "boundary_epoch_hash",
    "sensitivity_hash",
    "plan_hash",
    "plan_version_hash",
    "plan_digest_hash",
)
TASK_PUBLIC_FIELDS: Final[tuple[str, ...]] = (
    "session_id",
    "project_id",
    "worktree_id",
    "branch",
    "objective_hash",
    "boundary_epoch",
    "sensitivity",
    "plan_id",
    "plan_version",
    "plan_digest",
)
TASK_IDENTITY_FIELDS: Final[frozenset[str]] = frozenset((*TASK_HASH_FIELDS, *TASK_PUBLIC_FIELDS))
STATE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "policy_version",
        "policy_hash",
        "plan_id",
        "plan_version",
        "plan_digest",
        "task_id",
        "task_identity",
        "goal_id",
        "task_epoch",
        "boundary_epoch",
        "boundary_kind",
        "risk",
        "activation_mode",
        "phase",
        "status",
        "execution_lease",
        "previous_state_hash",
        "state_hash",
        "generation",
        "aristotle",
        "guards",
        "recall",
        "review",
        "failure_budget",
        "stop_budget",
        "invalidation_reason",
        "terminal_reason",
        "final_audit_digest",
        "completion",
    }
)
EVENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "sequence",
        "operation_id",
        "generation",
        "transition",
        "precondition_digest",
        "operation_digest",
        "state_patch",
        "evidence_ids",
        "policy_hash",
        "previous_state_hash",
        "new_state_hash",
        "previous_event_hash",
        "event_hash",
        "actor_role",
        "terminal_reason",
        "invalidation_reason",
    }
)
FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {"prompt", "raw_prompt", "body", "content", "stdout", "stderr", "log", "reviewer_output", "secret", "token", "credential"}
)
FORBIDDEN_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "prompt",
        "rawprompt",
        "body",
        "content",
        "stdout",
        "stderr",
        "log",
        "logs",
        "revieweroutput",
        "secret",
        "secrets",
        "token",
        "tokens",
        "credential",
        "credentials",
        "apikey",
        "privatekey",
        "password",
        "authorization",
        "cookie",
    }
)


class ContractError(ValueError):
    """Raised when state or event data violates the v3 wire contract."""


class FutureExecutionSchemaError(FutureSchemaError):
    """Future schemas block mutation and are never downgraded."""


@dataclass(frozen=True)
class TaskIdentity:
    session_hash: str
    project_hash: str
    worktree_hash: str
    branch_hash: str
    objective_hash: str
    boundary_epoch_hash: str
    sensitivity_hash: str
    plan_hash: str
    plan_version_hash: str
    plan_digest_hash: str
    session_id: str
    project_id: str
    worktree_id: str
    branch: str
    boundary_epoch: int
    sensitivity: str
    plan_id: str
    plan_version: int
    plan_digest: str

    @classmethod
    def from_values(
        cls,
        *,
        session: object,
        project: object,
        worktree: object,
        branch: object,
        objective: object,
        boundary_epoch: object,
        sensitivity: object,
        plan: object,
        plan_version: object,
        plan_digest: object,
    ) -> "TaskIdentity":
        return cls(
            session_hash=digest_text(session),
            project_hash=digest_text(project),
            worktree_hash=digest_text(worktree),
            branch_hash=digest_text(branch),
            objective_hash=digest_text(objective),
            boundary_epoch_hash=digest_text(boundary_epoch),
            sensitivity_hash=digest_text(str(sensitivity).upper()),
            plan_hash=digest_text(plan),
            plan_version_hash=digest_text(plan_version),
            plan_digest_hash=digest_text(plan_digest),
            session_id=digest_text(session),
            project_id=digest_text(project),
            worktree_id=digest_text(worktree),
            branch=_identity_branch(branch),
            boundary_epoch=_identity_epoch(boundary_epoch),
            sensitivity=_identity_sensitivity(sensitivity),
            plan_id=_identity_plan(plan),
            plan_version=_identity_version(plan_version),
            plan_digest=_digest(plan_digest, "task_identity.plan_digest"),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionLease:
    lease_id: str
    implementation_owner: str
    authority_owner: str
    model: str
    effort: str
    toolset_fingerprint: str
    cwd_fingerprint: str
    branch_fingerprint: str
    task_epoch_fingerprint: str
    issued_generation: int
    active: bool = True
    revoked_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest_value(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_text(value: object) -> str:
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()


def state_hash(state: Mapping[str, Any]) -> str:
    projection = deepcopy(dict(state))
    projection.pop("state_hash", None)
    return digest_value(projection)


def event_hash(event: Mapping[str, Any]) -> str:
    projection = deepcopy(dict(event))
    projection.pop("event_hash", None)
    return digest_value(projection)


def new_state(
    *,
    policy: ExecutionPolicy,
    plan_id: str,
    plan_version: int,
    plan_digest: str,
    task_identity: TaskIdentity,
    goal_id: str,
    task_epoch: str,
    boundary_epoch: int,
    boundary_kind: str,
    risk: str = "low",
    activation_mode: str,
    obligations: Sequence[str] = (),
) -> dict[str, Any]:
    identity = task_identity.as_dict()
    state: dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "policy_version": policy.version,
        "policy_hash": policy.policy_hash,
        "plan_id": _identifier(plan_id, "plan_id"),
        "plan_version": _positive_int(plan_version, "plan_version"),
        "plan_digest": _digest(plan_digest, "plan_digest"),
        "task_id": digest_value(identity),
        "task_identity": identity,
        "goal_id": _identifier(goal_id, "goal_id"),
        "task_epoch": _identifier(task_epoch, "task_epoch"),
        "boundary_epoch": _positive_int(boundary_epoch, "boundary_epoch"),
        "boundary_kind": _enum(boundary_kind, BOUNDARY_KINDS, "boundary_kind"),
        "risk": _enum(risk, {"low", "material", "critical"}, "risk"),
        "activation_mode": _enum(activation_mode, ACTIVATION_MODES, "activation_mode"),
        "phase": "prompt_gate",
        "status": "active",
        "execution_lease": None,
        "previous_state_hash": "",
        "state_hash": "",
        "generation": 0,
        "aristotle": {
            "tier": "",
            "full_runs": 0,
            "amendments": 0,
            "decision_version": 0,
            "decision_fingerprint": "",
        },
        "guards": {
            "repo_boundary": "always-on-relevant-tool",
            "git_safety": "always-on-relevant-tool",
            "red_egress": "always",
            "stop_guard": "always-on-stop",
        },
        "recall": {
            "memory_generation": 0,
            "checkpoint_generation": 0,
            "selection_fingerprint": "",
            "selected_ids": [],
            "delta_emitted": False,
            "context_epoch": "",
        },
        "review": {
            "required": False,
            "passes": 0,
            "accepted_findings": [],
            "mitigation_batches": 0,
            "critical_final_passes": 0,
            "findings_digest": "",
        },
        "failure_budget": {
            "transient_reruns": 0,
            "code_repair_cycles": 0,
            "fingerprints": {},
            "reopens": 0,
            "repair_origin": "",
            "terminal_origin": "",
        },
        "stop_budget": {"ordinary_continuations": 0, "critical_continuations": 0},
        "invalidation_reason": "",
        "terminal_reason": "",
        "final_audit_digest": "",
        "completion": {
            "hard_gates_pass": False,
            "open_obligations": _identifiers(obligations, "open_obligations", MAX_OBLIGATIONS),
            "handoff_published": False,
            "handoff_digest": "",
            "evidence_manifest_digest": "",
            "final_audit_digest": "",
            "terminal_reason": "",
            "invalidation_reason": "",
        },
    }
    state["state_hash"] = state_hash(state)
    return validate_state(state)


def validate_state(value: Mapping[str, Any]) -> dict[str, Any]:
    obj = _mapping(value, "state")
    _closed_keys(obj, STATE_FIELDS, "state")
    schema = _integer(obj.get("schema_version"), "schema_version")
    if schema > STATE_SCHEMA_VERSION:
        raise FutureExecutionSchemaError("future execution state schema")
    if schema != STATE_SCHEMA_VERSION:
        raise ContractError("execution state schema must be v3")
    if _integer(obj.get("policy_version"), "policy_version") != POLICY_VERSION:
        raise ContractError("execution policy version must be v4")
    normalized: dict[str, Any] = {
        "schema_version": schema,
        "policy_version": POLICY_VERSION,
        "policy_hash": _digest(obj.get("policy_hash"), "policy_hash"),
        "plan_id": _identifier(obj.get("plan_id"), "plan_id"),
        "plan_version": _positive_int(obj.get("plan_version"), "plan_version"),
        "plan_digest": _digest(obj.get("plan_digest"), "plan_digest"),
        "task_id": _digest(obj.get("task_id"), "task_id"),
        "task_identity": _task_identity(obj.get("task_identity")),
        "goal_id": _identifier(obj.get("goal_id"), "goal_id"),
        "task_epoch": _identifier(obj.get("task_epoch"), "task_epoch"),
        "boundary_epoch": _positive_int(obj.get("boundary_epoch"), "boundary_epoch"),
        "boundary_kind": _enum(obj.get("boundary_kind"), BOUNDARY_KINDS, "boundary_kind"),
        "risk": _enum(obj.get("risk"), {"low", "material", "critical"}, "risk"),
        "activation_mode": _enum(obj.get("activation_mode"), ACTIVATION_MODES, "activation_mode"),
        "phase": _enum(obj.get("phase"), set(PHASES), "phase"),
        "status": _enum(obj.get("status"), STATUSES, "status"),
        "execution_lease": _lease(obj.get("execution_lease")),
        "previous_state_hash": _optional_digest(obj.get("previous_state_hash"), "previous_state_hash"),
        "state_hash": _digest(obj.get("state_hash"), "state_hash"),
        "generation": _nonnegative_int(obj.get("generation"), "generation"),
        "aristotle": _aristotle(obj.get("aristotle")),
        "guards": _guards(obj.get("guards")),
        "recall": _recall(obj.get("recall")),
        "review": _review(obj.get("review")),
        "failure_budget": _failure_budget(obj.get("failure_budget")),
        "stop_budget": _stop_budget(obj.get("stop_budget")),
        "invalidation_reason": _bounded_code(obj.get("invalidation_reason"), "invalidation_reason", optional=True),
        "terminal_reason": _bounded_code(obj.get("terminal_reason"), "terminal_reason", optional=True),
        "final_audit_digest": _optional_digest(obj.get("final_audit_digest"), "final_audit_digest"),
        "completion": _completion(obj.get("completion")),
    }
    if normalized["task_id"] != digest_value(normalized["task_identity"]):
        raise ContractError("task_id does not match task identity")
    identity = normalized["task_identity"]
    for field in ("plan_id", "plan_version", "plan_digest", "boundary_epoch"):
        if normalized[field] != identity[field]:
            raise ContractError(f"state/task identity drift: {field}")
    lease = normalized["execution_lease"]
    if lease is not None:
        if lease["branch_fingerprint"] != digest_text(identity["branch"]):
            raise ContractError("execution lease branch differs from task identity")
        if lease["cwd_fingerprint"] != identity["worktree_id"]:
            raise ContractError("execution lease CWD differs from task identity")
        if lease["task_epoch_fingerprint"] != digest_text(normalized["task_epoch"]):
            raise ContractError("execution lease task epoch differs from control state")
        if lease["issued_generation"] > normalized["generation"]:
            raise ContractError("execution lease was issued after the current generation")
    if normalized["phase"] not in {"prompt_gate", "blocked", "user_decision"} and (
        lease is None or lease["active"] is not True
    ):
        raise ContractError("active SOL/max execution lease is required after Prompt Gate")
    if normalized["status"] == "closed" and normalized["phase"] != "close":
        raise ContractError("closed status requires close phase")
    if normalized["phase"] == "close" and normalized["status"] != "closed":
        raise ContractError("close phase requires closed status")
    if (normalized["phase"] == "blocked") != (normalized["status"] == "blocked"):
        raise ContractError("blocked phase and status must agree")
    if (normalized["phase"] == "user_decision") != (normalized["status"] == "user-decision"):
        raise ContractError("user-decision phase and status must agree")
    for field in ("invalidation_reason", "terminal_reason", "final_audit_digest"):
        if normalized[field] != normalized["completion"][field]:
            raise ContractError(f"top-level {field} must mirror completion.{field}")
    if normalized["state_hash"] != state_hash(normalized):
        raise ContractError("execution state hash mismatch")
    _reject_forbidden(normalized, "state")
    if len(canonical_json(normalized).encode("utf-8")) > MAX_STATE_BYTES:
        raise ContractError("execution state exceeds its byte limit")
    return normalized


def make_event(
    *,
    operation_id: str,
    operation_digest: str,
    sequence: int,
    transition: str,
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    evidence_ids: Sequence[str] = (),
    previous_event_hash: str = "",
    actor_role: str = "deterministic-runtime",
) -> dict[str, Any]:
    before = validate_state(previous)
    after = validate_state(current)
    event: dict[str, Any] = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "sequence": sequence,
        "operation_id": _identifier(operation_id, "operation_id"),
        "generation": after["generation"],
        "transition": _enum(transition, TRANSITIONS, "transition"),
        "precondition_digest": before["state_hash"],
        "operation_digest": _digest(operation_digest, "operation_digest"),
        "state_patch": _state_patch(before, after),
        "evidence_ids": _identifiers(evidence_ids, "evidence_ids", MAX_EVIDENCE_IDS),
        "policy_hash": after["policy_hash"],
        "previous_state_hash": before["state_hash"],
        "new_state_hash": after["state_hash"],
        "previous_event_hash": _optional_digest(previous_event_hash, "previous_event_hash"),
        "event_hash": "",
        "actor_role": _enum(actor_role, ACTOR_ROLES, "actor_role"),
        "terminal_reason": after["completion"]["terminal_reason"],
        "invalidation_reason": after["completion"]["invalidation_reason"],
    }
    event["event_hash"] = event_hash(event)
    return validate_event(event)


def validate_event(value: Mapping[str, Any]) -> dict[str, Any]:
    obj = _mapping(value, "event")
    _closed_keys(obj, EVENT_FIELDS, "event")
    schema = _integer(obj.get("schema_version"), "schema_version")
    if schema > EVENT_SCHEMA_VERSION:
        raise FutureExecutionSchemaError("future execution event schema")
    if schema != EVENT_SCHEMA_VERSION:
        raise ContractError("execution event schema must be v3")
    normalized = {
        "schema_version": schema,
        "sequence": _positive_int(obj.get("sequence"), "sequence"),
        "operation_id": _identifier(obj.get("operation_id"), "operation_id"),
        "generation": _positive_int(obj.get("generation"), "generation"),
        "transition": _enum(obj.get("transition"), TRANSITIONS, "transition"),
        "precondition_digest": _digest(obj.get("precondition_digest"), "precondition_digest"),
        "operation_digest": _digest(obj.get("operation_digest"), "operation_digest"),
        "state_patch": _validate_state_patch(obj.get("state_patch")),
        "evidence_ids": _identifiers(obj.get("evidence_ids"), "evidence_ids", MAX_EVIDENCE_IDS),
        "policy_hash": _digest(obj.get("policy_hash"), "policy_hash"),
        "previous_state_hash": _digest(obj.get("previous_state_hash"), "previous_state_hash"),
        "new_state_hash": _digest(obj.get("new_state_hash"), "new_state_hash"),
        "previous_event_hash": _optional_digest(obj.get("previous_event_hash"), "previous_event_hash"),
        "event_hash": _digest(obj.get("event_hash"), "event_hash"),
        "actor_role": _enum(obj.get("actor_role"), ACTOR_ROLES, "actor_role"),
        "terminal_reason": _bounded_code(obj.get("terminal_reason"), "terminal_reason", optional=True),
        "invalidation_reason": _bounded_code(obj.get("invalidation_reason"), "invalidation_reason", optional=True),
    }
    patch = normalized["state_patch"]
    if normalized["precondition_digest"] != normalized["previous_state_hash"]:
        raise ContractError("event precondition_digest must equal previous_state_hash")
    if patch.get("generation") != normalized["generation"]:
        raise ContractError("event state_patch generation does not match event generation")
    if patch.get("previous_state_hash") != normalized["previous_state_hash"]:
        raise ContractError("event state_patch previous_state_hash does not match its precondition")
    completion_patch = patch.get("completion")
    if isinstance(completion_patch, Mapping):
        if completion_patch.get("terminal_reason") != normalized["terminal_reason"]:
            raise ContractError("event terminal_reason differs from its state patch")
        if completion_patch.get("invalidation_reason") != normalized["invalidation_reason"]:
            raise ContractError("event invalidation_reason differs from its state patch")
    for reason in ("terminal_reason", "invalidation_reason"):
        if reason in patch and patch[reason] != normalized[reason]:
            raise ContractError(f"event {reason} differs from its top-level state patch")
    if normalized["event_hash"] != event_hash(normalized):
        raise ContractError("execution event hash mismatch")
    _reject_forbidden(normalized, "event")
    if len(canonical_json(normalized).encode("utf-8")) + 1 > MAX_EVENT_BYTES:
        raise ContractError("execution event exceeds its byte limit")
    return normalized


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return value


def _closed_keys(obj: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(obj) - set(allowed))
    missing = sorted(set(allowed) - set(obj))
    if unknown:
        raise ContractError(f"{label} has unknown keys: {', '.join(unknown)}")
    if missing:
        raise ContractError(f"{label} is missing keys: {', '.join(missing)}")


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{label} must be an integer")
    return value


def _positive_int(value: object, label: str) -> int:
    value = _integer(value, label)
    if value < 1:
        raise ContractError(f"{label} must be positive")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    value = _integer(value, label)
    if value < 0:
        raise ContractError(f"{label} must be nonnegative")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise ContractError(f"{label} must be a safe bounded identifier")
    return value


def _identity_branch(value: object) -> str:
    return _identifier(value, "task_identity.branch")


def _identity_epoch(value: object) -> int:
    return _positive_int(value, "task_identity.boundary_epoch")


def _identity_sensitivity(value: object) -> str:
    return _enum(str(value).upper(), {"GREEN", "YELLOW", "RED"}, "task_identity.sensitivity")


def _identity_plan(value: object) -> str:
    return _identifier(value, "task_identity.plan_id")


def _identity_version(value: object) -> int:
    return _positive_int(value, "task_identity.plan_version")


def _identifiers(value: object, label: str, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > limit:
        raise ContractError(f"{label} must be a bounded identifier array")
    result = [_identifier(item, f"{label} item") for item in value]
    if len(set(result)) != len(result):
        raise ContractError(f"{label} contains duplicates")
    return result


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ContractError(f"{label} must be a sha256 digest")
    return value


def _optional_digest(value: object, label: str) -> str:
    return "" if value in (None, "") else _digest(value, label)


def _enum(value: object, allowed: set[str] | frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ContractError(f"{label} has an unsupported value")
    return value


def _bounded_code(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value in (None, ""):
        return ""
    return _identifier(value, label)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{label} must be boolean")
    return value


def _task_identity(value: object) -> dict[str, Any]:
    obj = _mapping(value, "task_identity")
    _closed_keys(obj, TASK_IDENTITY_FIELDS, "task_identity")
    normalized: dict[str, Any] = {field: _digest(obj.get(field), f"task_identity.{field}") for field in TASK_HASH_FIELDS}
    normalized.update(
        {
            "session_id": _digest(obj.get("session_id"), "task_identity.session_id"),
            "project_id": _digest(obj.get("project_id"), "task_identity.project_id"),
            "worktree_id": _digest(obj.get("worktree_id"), "task_identity.worktree_id"),
            "branch": _identity_branch(obj.get("branch")),
            "objective_hash": _digest(obj.get("objective_hash"), "task_identity.objective_hash"),
            "boundary_epoch": _identity_epoch(obj.get("boundary_epoch")),
            "sensitivity": _identity_sensitivity(obj.get("sensitivity")),
            "plan_id": _identity_plan(obj.get("plan_id")),
            "plan_version": _identity_version(obj.get("plan_version")),
            "plan_digest": _digest(obj.get("plan_digest"), "task_identity.plan_digest"),
        }
    )
    aliases = {
        "session_id": "session_hash",
        "project_id": "project_hash",
        "worktree_id": "worktree_hash",
        "branch": "branch_hash",
        "objective_hash": "objective_hash",
        "sensitivity": "sensitivity_hash",
        "plan_id": "plan_hash",
        "plan_version": "plan_version_hash",
    }
    for public, legacy in aliases.items():
        expected = normalized[public] if public in {"session_id", "project_id", "worktree_id", "objective_hash"} else digest_text(normalized[public])
        if normalized[legacy] != expected:
            raise ContractError(f"task identity alias drift: {public}")
    if normalized["plan_digest_hash"] != digest_text(normalized["plan_digest"]):
        raise ContractError("task identity plan digest alias drift")
    if normalized["boundary_epoch_hash"] != digest_text(normalized["boundary_epoch"]):
        raise ContractError("task identity boundary epoch alias drift")
    if normalized["sensitivity_hash"] != digest_text(normalized["sensitivity"]):
        raise ContractError("task identity sensitivity alias drift")
    if normalized["plan_id"] and normalized["plan_hash"] != digest_text(normalized["plan_id"]):
        raise ContractError("task identity plan alias drift")
    if normalized["plan_version_hash"] != digest_text(normalized["plan_version"]):
        raise ContractError("task identity plan version alias drift")
    if normalized["branch_hash"] != digest_text(normalized["branch"]):
        raise ContractError("task identity branch alias drift")
    return normalized


def _lease(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    obj = _mapping(value, "execution_lease")
    fields = frozenset(
        {
            "lease_id",
            "implementation_owner",
            "authority_owner",
            "model",
            "effort",
            "toolset_fingerprint",
            "cwd_fingerprint",
            "branch_fingerprint",
            "task_epoch_fingerprint",
            "issued_generation",
            "active",
            "revoked_reason",
        }
    )
    _closed_keys(obj, fields, "execution_lease")
    result = {
        "lease_id": _identifier(obj.get("lease_id"), "execution_lease.lease_id"),
        "implementation_owner": _enum(obj.get("implementation_owner"), {IMPLEMENTATION_ROLE}, "execution_lease.implementation_owner"),
        "authority_owner": _enum(obj.get("authority_owner"), {AUTHORITY_ROLE}, "execution_lease.authority_owner"),
        "model": _enum(obj.get("model"), {REQUIRED_IMPLEMENTATION_MODEL}, "execution_lease.model"),
        "effort": _enum(obj.get("effort"), {REQUIRED_REASONING_EFFORT}, "execution_lease.effort"),
        "toolset_fingerprint": _digest(obj.get("toolset_fingerprint"), "execution_lease.toolset_fingerprint"),
        "cwd_fingerprint": _digest(obj.get("cwd_fingerprint"), "execution_lease.cwd_fingerprint"),
        "branch_fingerprint": _digest(obj.get("branch_fingerprint"), "execution_lease.branch_fingerprint"),
        "task_epoch_fingerprint": _digest(obj.get("task_epoch_fingerprint"), "execution_lease.task_epoch_fingerprint"),
        "issued_generation": _nonnegative_int(obj.get("issued_generation"), "execution_lease.issued_generation"),
        "active": _boolean(obj.get("active"), "execution_lease.active"),
        "revoked_reason": _bounded_code(obj.get("revoked_reason"), "execution_lease.revoked_reason", optional=True),
    }
    if result["active"] and result["revoked_reason"]:
        raise ContractError("active execution lease cannot be revoked")
    material = {
        "model": result["model"],
        "effort": result["effort"],
        "toolset_fingerprint": result["toolset_fingerprint"],
        "cwd_fingerprint": result["cwd_fingerprint"],
        "branch_fingerprint": result["branch_fingerprint"],
        "task_epoch_fingerprint": result["task_epoch_fingerprint"],
        "implementation_owner": result["implementation_owner"],
        "authority_owner": result["authority_owner"],
        "issued_generation": result["issued_generation"],
    }
    expected_lease_id = "lease-" + digest_value(material).split(":", 1)[1][:32]
    if result["lease_id"] != expected_lease_id:
        raise ContractError("execution lease ID does not match its immutable evidence")
    return result


def _aristotle(value: object) -> dict[str, Any]:
    obj = _mapping(value, "aristotle")
    fields = frozenset({"tier", "full_runs", "amendments", "decision_version", "decision_fingerprint"})
    _closed_keys(obj, fields, "aristotle")
    tier = obj.get("tier")
    if tier != "":
        tier = _enum(tier, {"micro", "quick", "full", "critical"}, "aristotle.tier")
    result = {
        "tier": tier,
        "full_runs": _nonnegative_int(obj.get("full_runs"), "aristotle.full_runs"),
        "amendments": _nonnegative_int(obj.get("amendments"), "aristotle.amendments"),
        "decision_version": _nonnegative_int(obj.get("decision_version"), "aristotle.decision_version"),
        "decision_fingerprint": _optional_digest(obj.get("decision_fingerprint"), "aristotle.decision_fingerprint"),
    }
    maximum_full = int(POLICY_SPEC["aristotle"]["full_runs_per_task"])
    maximum_amendments = int(POLICY_SPEC["aristotle"]["material_amendments_per_task"])
    if result["full_runs"] > maximum_full or result["amendments"] > maximum_amendments:
        raise ContractError("Aristotle state exceeds the supplied v4 budget")
    if result["decision_version"] > maximum_full + maximum_amendments:
        raise ContractError("Decision Packet version exceeds the supplied v4 budget")
    return result


def _guards(value: object) -> dict[str, str]:
    obj = _mapping(value, "guards")
    expected = {
        "repo_boundary": "always-on-relevant-tool",
        "git_safety": "always-on-relevant-tool",
        "red_egress": "always",
        "stop_guard": "always-on-stop",
    }
    _closed_keys(obj, frozenset(expected), "guards")
    if dict(obj) != expected:
        raise ContractError("guard invariants cannot be weakened")
    return expected


def _recall(value: object) -> dict[str, Any]:
    obj = _mapping(value, "recall")
    fields = frozenset(
        {"memory_generation", "checkpoint_generation", "selection_fingerprint", "selected_ids", "delta_emitted", "context_epoch"}
    )
    _closed_keys(obj, fields, "recall")
    return {
        "memory_generation": _nonnegative_int(obj.get("memory_generation"), "recall.memory_generation"),
        "checkpoint_generation": _nonnegative_int(obj.get("checkpoint_generation"), "recall.checkpoint_generation"),
        "selection_fingerprint": _optional_digest(obj.get("selection_fingerprint"), "recall.selection_fingerprint"),
        "selected_ids": _identifiers(obj.get("selected_ids"), "recall.selected_ids", 64),
        "delta_emitted": _boolean(obj.get("delta_emitted"), "recall.delta_emitted"),
        "context_epoch": _bounded_code(obj.get("context_epoch"), "recall.context_epoch", optional=True),
    }


def _review(value: object) -> dict[str, Any]:
    obj = _mapping(value, "review")
    fields = frozenset(
        {"required", "passes", "accepted_findings", "mitigation_batches", "critical_final_passes", "findings_digest"}
    )
    _closed_keys(obj, fields, "review")
    result = {
        "required": _boolean(obj.get("required"), "review.required"),
        "passes": _nonnegative_int(obj.get("passes"), "review.passes"),
        "accepted_findings": _identifiers(obj.get("accepted_findings"), "review.accepted_findings", 64),
        "mitigation_batches": _nonnegative_int(obj.get("mitigation_batches"), "review.mitigation_batches"),
        "critical_final_passes": _nonnegative_int(obj.get("critical_final_passes"), "review.critical_final_passes"),
        "findings_digest": _optional_digest(obj.get("findings_digest"), "review.findings_digest"),
    }
    maximum = int(POLICY_SPEC["review"]["automatic_passes_material"])
    if result["passes"] > maximum or result["mitigation_batches"] > 1 or result["critical_final_passes"] > 1:
        raise ContractError("review state exceeds the supplied v4 budget")
    return result


def _failure_budget(value: object) -> dict[str, Any]:
    obj = _mapping(value, "failure_budget")
    fields = frozenset(
        {"transient_reruns", "code_repair_cycles", "fingerprints", "reopens", "repair_origin", "terminal_origin"}
    )
    _closed_keys(obj, fields, "failure_budget")
    fingerprints = _mapping(obj.get("fingerprints"), "failure_budget.fingerprints")
    if len(fingerprints) > 64:
        raise ContractError("failure fingerprint map exceeds its limit")
    result = {
        "transient_reruns": _nonnegative_int(obj.get("transient_reruns"), "failure_budget.transient_reruns"),
        "code_repair_cycles": _nonnegative_int(obj.get("code_repair_cycles"), "failure_budget.code_repair_cycles"),
        "fingerprints": {_digest(key, "failure fingerprint"): _nonnegative_int(count, "failure count") for key, count in fingerprints.items()},
        "reopens": _nonnegative_int(obj.get("reopens"), "failure_budget.reopens"),
        "repair_origin": _enum(
            obj.get("repair_origin"), {"", "verify", "final_audit", "stop"}, "failure_budget.repair_origin"
        ),
        "terminal_origin": _enum(
            obj.get("terminal_origin"), (set(PHASES) - {"close"}) | {""}, "failure_budget.terminal_origin"
        ),
    }
    repair = POLICY_SPEC["repair"]
    if result["transient_reruns"] > int(repair["transient_identical_reruns"]):
        raise ContractError("transient rerun state exceeds the supplied v4 budget")
    if result["code_repair_cycles"] > int(repair["maximum_total_repair_cycles"]):
        raise ContractError("repair state exceeds the supplied v4 total budget")
    if any(count > int(repair["repairs_per_failure_fingerprint"]) for count in result["fingerprints"].values()):
        raise ContractError("failure fingerprint state exceeds the supplied v4 budget")
    if sum(result["fingerprints"].values()) != result["code_repair_cycles"]:
        raise ContractError("repair counters do not match failure fingerprint evidence")
    if result["reopens"] > int(POLICY_SPEC["execution"]["max_task_reopens"]):
        raise ContractError("reopen state exceeds the supplied v4 budget")
    return result


def _stop_budget(value: object) -> dict[str, int]:
    obj = _mapping(value, "stop_budget")
    fields = frozenset({"ordinary_continuations", "critical_continuations"})
    _closed_keys(obj, fields, "stop_budget")
    result = {
        "ordinary_continuations": _nonnegative_int(obj.get("ordinary_continuations"), "stop_budget.ordinary_continuations"),
        "critical_continuations": _nonnegative_int(obj.get("critical_continuations"), "stop_budget.critical_continuations"),
    }
    if result["ordinary_continuations"] > int(POLICY_SPEC["stop"]["ordinary_continuations"]):
        raise ContractError("ordinary Stop state exceeds the supplied v4 budget")
    if result["critical_continuations"] > int(POLICY_SPEC["stop"]["distinct_critical_continuations"]):
        raise ContractError("critical Stop state exceeds the supplied v4 budget")
    return result


def _completion(value: object) -> dict[str, Any]:
    obj = _mapping(value, "completion")
    fields = frozenset(
        {
            "hard_gates_pass",
            "open_obligations",
            "handoff_published",
            "handoff_digest",
            "evidence_manifest_digest",
            "final_audit_digest",
            "terminal_reason",
            "invalidation_reason",
        }
    )
    _closed_keys(obj, fields, "completion")
    return {
        "hard_gates_pass": _boolean(obj.get("hard_gates_pass"), "completion.hard_gates_pass"),
        "open_obligations": _identifiers(obj.get("open_obligations"), "completion.open_obligations", MAX_OBLIGATIONS),
        "handoff_published": _boolean(obj.get("handoff_published"), "completion.handoff_published"),
        "handoff_digest": _optional_digest(obj.get("handoff_digest"), "completion.handoff_digest"),
        "evidence_manifest_digest": _optional_digest(obj.get("evidence_manifest_digest"), "completion.evidence_manifest_digest"),
        "final_audit_digest": _optional_digest(obj.get("final_audit_digest"), "completion.final_audit_digest"),
        "terminal_reason": _bounded_code(obj.get("terminal_reason"), "completion.terminal_reason", optional=True),
        "invalidation_reason": _bounded_code(obj.get("invalidation_reason"), "completion.invalidation_reason", optional=True),
    }


def _state_patch(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(after[key])
        for key in sorted(STATE_FIELDS)
        if key != "state_hash" and before.get(key) != after.get(key)
    }


def _validate_state_patch(value: object) -> dict[str, Any]:
    obj = _mapping(value, "state_patch")
    allowed = set(STATE_FIELDS) - {
        "schema_version",
        "policy_version",
        "policy_hash",
        "plan_id",
        "plan_version",
        "plan_digest",
        "task_id",
        "task_identity",
        "goal_id",
        "task_epoch",
        "boundary_epoch",
        "boundary_kind",
        "activation_mode",
        "state_hash",
    }
    unknown = sorted(set(obj) - allowed)
    if unknown or not obj:
        raise ContractError("state_patch is empty or changes immutable fields")
    validators = {
        "phase": lambda item: _enum(item, set(PHASES), "state_patch.phase"),
        "status": lambda item: _enum(item, STATUSES, "state_patch.status"),
        "risk": lambda item: _enum(item, {"low", "material", "critical"}, "state_patch.risk"),
        "execution_lease": _lease,
        "previous_state_hash": lambda item: _digest(item, "state_patch.previous_state_hash"),
        "generation": lambda item: _positive_int(item, "state_patch.generation"),
        "aristotle": _aristotle,
        "guards": _guards,
        "recall": _recall,
        "review": _review,
        "failure_budget": _failure_budget,
        "stop_budget": _stop_budget,
        "invalidation_reason": lambda item: _bounded_code(item, "state_patch.invalidation_reason", optional=True),
        "terminal_reason": lambda item: _bounded_code(item, "state_patch.terminal_reason", optional=True),
        "final_audit_digest": lambda item: _optional_digest(item, "state_patch.final_audit_digest"),
        "completion": _completion,
    }
    normalized = {key: validators[key](item) for key, item in obj.items()}
    _reject_forbidden(normalized, "state_patch")
    return normalized


def _reject_forbidden(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            compact_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
            if str(key).lower() in FORBIDDEN_KEYS or compact_key in FORBIDDEN_KEY_TOKENS:
                raise ContractError(f"{label} contains forbidden field {key}")
            _reject_forbidden(item, label)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_forbidden(item, label)
    elif isinstance(value, str) and value and not SHA256_RE.fullmatch(value) and is_red(value):
        raise ContractError(f"{label} contains RED material")


__all__ = [
    "ACTIVATION_MODES",
    "ACTOR_ROLES",
    "BOUNDARY_KINDS",
    "ContractError",
    "EVENT_SCHEMA_VERSION",
    "ExecutionLease",
    "FutureExecutionSchemaError",
    "MAX_EVENT_BYTES",
    "MAX_STATE_BYTES",
    "PHASES",
    "STATE_SCHEMA_VERSION",
    "TASK_HASH_FIELDS",
    "TASK_PUBLIC_FIELDS",
    "TASK_IDENTITY_FIELDS",
    "TRANSITIONS",
    "TaskIdentity",
    "canonical_json",
    "digest_text",
    "digest_value",
    "event_hash",
    "make_event",
    "new_state",
    "state_hash",
    "validate_event",
    "validate_state",
]
