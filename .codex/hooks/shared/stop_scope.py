from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .active_context import ActiveContext, active_context_from_payload

SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 24 * 60 * 60
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_SAFE_TASK_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


@dataclass(frozen=True)
class StopScope:
    context: ActiveContext
    task_signature: str
    task_identity_present: bool
    turn_id: str
    scope_key: str


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first(payload: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = _text(payload.get(key))
        if value:
            return value
    return ""


def _digest(value: str, length: int = 32) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def _safe_component(value: str, limit: int = 80) -> str:
    return _SAFE_ID_RE.sub("_", value).strip("_.-")[:limit] or "unknown"


def _normalized_objective(payload: Mapping[str, object]) -> str:
    value = _first(
        payload,
        "objective",
        "task",
        "task_id",
        "taskId",
        "objective_id",
        "objectiveId",
        "implementation_plan_path",
        "implementationPlanPath",
        "plan_path",
        "planPath",
    )
    return " ".join(value.split())[:2000]


def task_signature_for_payload(payload: Mapping[str, object], context: ActiveContext) -> tuple[str, bool]:
    explicit = _first(payload, "task_signature", "taskSignature", "task_fingerprint", "taskFingerprint")
    objective = _normalized_objective(payload)
    if explicit:
        # Explicit opaque fingerprints are already identifiers. Preserve safe
        # values so separate events do not hash the same task repeatedly.
        if _SAFE_TASK_RE.fullmatch(explicit):
            return explicit, True
        return f"task-{_digest(explicit)}", True
    if objective:
        return f"task-{_digest(objective)}", True
    fallback = "|".join((context.project_id, context.workspace_instance_id, context.branch, context.session_id))
    return f"session-{_digest(fallback)}", False


def scope_from_payload(payload: Mapping[str, object]) -> StopScope:
    context = active_context_from_payload(dict(payload), resolve_git=False)
    task_signature, present = task_signature_for_payload(payload, context)
    turn_id = _first(payload, "turn_id", "turnId", "event_id", "eventId") or "turn-unknown"
    # The continuation budget is task-scoped.  A new Stop event/turn for the
    # same session task must not reset the ordinary-continuation allowance;
    # ``turn_id`` remains available in the persisted event for diagnostics.
    material = "|".join(
        (
            str(SCHEMA_VERSION),
            context.project_id,
            context.workspace_instance_id,
            context.branch,
            context.session_id,
            task_signature,
        )
    )
    return StopScope(
        context=context,
        task_signature=task_signature,
        task_identity_present=present,
        turn_id=_safe_component(turn_id),
        scope_key=_digest(material),
    )


def scope_from_convergent_state(payload: Mapping[str, object], state: Mapping[str, object]) -> StopScope:
    """Build a v4 terminal scope without binding it to a Codex session.

    Session IDs remain provenance on the context, but the canonical task
    identity is plan/task/worktree scoped. A resumed task must find the same
    terminal marker in a new CLI or App session.
    """

    context = active_context_from_payload(dict(payload), resolve_git=False)
    identity = state.get("task_identity") if isinstance(state.get("task_identity"), Mapping) else {}
    task_id = str(state.get("task_id") or "")
    task_epoch = str(state.get("task_epoch") or "")
    persisted_branch = str(identity.get("branch") or context.branch)
    persisted_worktree = str(identity.get("worktree_id") or context.workspace_instance_id)
    material = "|".join(
        (
            str(SCHEMA_VERSION),
            context.project_id,
            persisted_worktree,
            persisted_branch,
            task_id,
            task_epoch,
        )
    )
    return StopScope(
        context=context,
        task_signature=task_id,
        task_identity_present=bool(task_id),
        turn_id=_safe_component(_first(payload, "turn_id", "turnId", "event_id", "eventId") or "turn-unknown"),
        scope_key=_digest(material),
    )


def parse_timestamp(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def state_ttl_seconds() -> int:
    raw = os.environ.get("RALPH_STOP_STATE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TTL_SECONDS
    return max(60, min(value, 7 * 24 * 60 * 60))


def state_is_fresh(state: Mapping[str, object], path: Path | None = None, now: float | None = None) -> bool:
    now_value = now if now is not None else datetime.now(UTC).timestamp()
    stamp = parse_timestamp(
        state.get("updated_at")
        or state.get("updatedAt")
        or state.get("created_at")
        or state.get("createdAt")
        or state.get("timestamp")
    )
    if stamp is None and path is not None:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return False
    if stamp is None:
        return False
    return 0 <= now_value - stamp <= state_ttl_seconds()


def state_matches_scope(state: Mapping[str, object], scope: StopScope) -> tuple[bool, str]:
    session = _first(state, "session_id", "sessionId", "codex_session_id", "codexSessionId")
    task = _first(state, "task_signature", "taskSignature", "task_fingerprint", "taskFingerprint")
    workspace = _first(state, "workspace_root", "workspaceRoot", "cwd", "workdir")
    project_id = _first(state, "project_id", "projectId")

    # A state record without both identities is advisory only. A current
    # payload task must not turn an unscoped/possibly foreign record into a
    # blocking hard gate.
    if not session or not task:
        return False, "unscoped"
    if session != scope.context.session_id:
        return False, "foreign_session"
    compatible_tasks = {
        scope.task_signature,
        _digest(scope.task_signature),
        f"task-{_digest(scope.task_signature)}",
    }
    if task and task not in compatible_tasks:
        return False, "foreign_task"
    if workspace:
        try:
            if Path(workspace).expanduser().resolve(strict=False) != scope.context.workspace_root.resolve(strict=False):
                return False, "foreign_workspace"
        except OSError:
            return False, "foreign_workspace"
    if project_id and project_id != scope.context.project_id:
        return False, "foreign_project"
    branch = _first(state, "branch", "git_branch")
    if branch and branch != scope.context.branch:
        return False, "foreign_branch"
    sha = _first(state, "sha", "git_sha", "head")
    if sha and scope.context.sha and not (
        scope.context.sha.startswith(sha) or sha.startswith(scope.context.sha)
    ):
        return False, "foreign_head"
    return True, "matched"


def evidence_fingerprint(parts: list[str]) -> str:
    return _digest("|".join(sorted(part for part in parts if part)))
