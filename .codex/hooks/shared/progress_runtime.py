"""Narrow lifecycle integration for the canonical implementation-progress store.

This module is deliberately an adapter, not a second progress implementation.
It recognizes structured validation outcomes, asks the canonical store to apply
semantic transitions, and exposes only bounded writer metadata to hook callers.
No legacy view, note, or archive writer is reachable from these functions.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .active_context import ActiveContext
from .implementation_store import (
    CorruptRecordError,
    FutureSchemaError,
    IntegrityError,
    SchemaError,
    StoreError,
)
from .persistence_metrics import WriteResult
from .progress_hook import ProgressLookup, cheap_lookup
from .redaction import is_red, safe_preview
from .runtime_profile import profile_from_payload

# ``progress_hook`` resolves the canonical engine root for both project-local
# and installed hook copies before importing the pure context engine. Reuse
# that path setup rather than shipping a second implementation into hooks.
from implementation_notes_lib import ImplementationNotesError, is_plan_approved, parse_plan_metadata_text


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")
_PLAN_KEYS = ("progress_plan_id", "progressPlanId")
_PLAN_PATH_KEYS = (
    "implementation_plan_path",
    "implementationPlanPath",
    "plan_path",
    "planPath",
)
_APPROVAL_KEYS = (
    "plan_approved",
    "planApproved",
    "implementation_plan_approved",
    "implementationPlanApproved",
)
_COMPLETION_KEYS = (
    "progress_complete",
    "progressComplete",
    "implementation_complete",
    "implementationComplete",
    "completion_verified",
    "completionVerified",
    "task_complete",
    "taskComplete",
    "verified_done",
    "verifiedDone",
    "completed",
)


@dataclass(frozen=True)
class ValidationTransition:
    result: WriteResult = WriteResult()
    gate: str = ""
    status: str = ""
    changed: bool = False
    reason: str = ""


@dataclass(frozen=True)
class CompletionTransition:
    result: WriteResult = WriteResult()
    changed: bool = False
    in_scope: bool = False
    error_code: str = ""
    error_reason: str = ""
    reason: str = ""


def _value(payload: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _text(value: object, limit: int = 240) -> str:
    return " ".join(safe_preview(value, limit=limit).split()) if value is not None else ""


def _safe_id(value: object, default: str = "") -> str:
    text = str(value or "").strip()
    return text if _ID_RE.fullmatch(text) else default


def _tool_input(payload: Mapping[str, object]) -> Mapping[str, object]:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _command(payload: Mapping[str, object]) -> str:
    nested = _tool_input(payload)
    for value in (
        payload.get("command"),
        payload.get("cmd"),
        nested.get("command"),
        nested.get("cmd"),
    ):
        if isinstance(value, str) and value.strip():
            return _text(value, 500)
    return ""


def _tool_name(payload: Mapping[str, object]) -> str:
    return _text(payload.get("tool_name") or payload.get("toolName") or payload.get("tool"), 120).lower()


def _safe_plan_metadata(path: Path, root: Path):
    """Read one plan document without following aliases or unbounded bodies."""

    lexical = path.absolute()
    try:
        lexical.relative_to(root)
    except ValueError:
        return None
    current = Path(lexical.parts[0])
    for part in lexical.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return None
        if stat.S_ISLNK(info.st_mode):
            return None
    try:
        fd = os.open(lexical, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 256 * 1024:
            return None
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, 256 * 1024 - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > 256 * 1024:
                return None
        final = os.fstat(fd)
        if final.st_dev != info.st_dev or final.st_ino != info.st_ino or final.st_nlink != 1 or final.st_size != total:
            return None
        text = b"".join(chunks).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        os.close(fd)
    try:
        return parse_plan_metadata_text(text)
    except (ImplementationNotesError, OSError, ValueError):
        return None


def _gate_for(payload: Mapping[str, object]) -> str:
    name = _tool_name(payload)
    command = _command(payload).lower()
    name_tokens = set(re.findall(r"[a-z0-9]+", name))
    try:
        command_tokens = [token.lower() for token in shlex.split(command)]
    except ValueError:
        command_tokens = []

    explicit = payload.get("validation_gate") or payload.get("validationGate") or payload.get("gate")
    if isinstance(explicit, str) and explicit.strip().lower() in {"tests", "test", "build", "lint", "typecheck"}:
        return "tests" if explicit.strip().lower() == "test" else explicit.strip().lower()

    command_names = [Path(token).name.lower() for token in command_tokens]
    executable = command_names[0] if command_names else ""
    shell_separators = {"&&", "||", ";", "|"}

    def direct_runner(names: set[str]) -> bool:
        for index, token in enumerate(command_names):
            if token not in names:
                continue
            if index == 0 or command_tokens[index - 1] in shell_separators:
                return True
            if index and command_tokens[index - 1] == "-m":
                return True
            if index and command_names[index - 1] in {"npx", "uv", "poetry"}:
                return True
            if index > 1 and command_names[index - 2] in {"uv", "poetry"}:
                return True
        return False

    script_runner = {"npm", "pnpm", "yarn", "make", "just"}
    if name_tokens & {"lint", "ruff", "flake8", "eslint", "prettier"} or direct_runner({"lint", "ruff", "flake8", "eslint", "prettier"}) or executable in script_runner and "lint" in command_names[1:]:
        return "lint"
    if name_tokens & {"typecheck", "mypy", "pyright", "tsc"} or direct_runner({"typecheck", "mypy", "pyright", "tsc"}) or executable in script_runner and "typecheck" in command_names[1:]:
        return "typecheck"
    if name_tokens & {"build", "compile", "gradle"} or executable in script_runner | {"gradle", "gradlew"} and any(token in {"build", "compile"} for token in command_names[1:]) or direct_runner({"build", "compile"}) or executable == "cargo" and "check" in command_names:
        return "build"
    test_runner = direct_runner({"pytest", "unittest", "jest", "vitest"})
    test_runner = test_runner or executable in {"npm", "pnpm", "yarn", "make", "go", "cargo"} and "test" in command_names[1:]
    if name_tokens & {"test", "tests", "pytest", "unittest", "jest", "vitest"} or test_runner:
        return "tests"
    return ""


def _structured_status(payload: Mapping[str, object]) -> str:
    """Return pass/fail only for an explicit structured tool result."""

    mappings: list[Mapping[str, object]] = [payload]
    for key in ("tool_response", "toolResponse", "result"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            mappings.append(value)
    for mapping in mappings:
        value = mapping.get("success")
        if isinstance(value, bool):
            return "pass" if value else "fail"
        for key in ("exit_code", "returncode", "return_code"):
            value = mapping.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return "pass" if value == 0 else "fail"
        value = mapping.get("status")
        if isinstance(value, str) and value.strip().lower() in {"pass", "passed", "success", "ok", "fail", "failed", "error"}:
            return "pass" if value.strip().lower() in {"pass", "passed", "success", "ok"} else "fail"
    return ""


def structured_validation(payload: Mapping[str, object]) -> tuple[str, str] | None:
    """Recognize only test/build/lint-like tools with explicit outcomes."""

    if str(payload.get("hook_event_name") or payload.get("hookEventName") or "PostToolUse") not in {"", "PostToolUse"}:
        return None
    gate = _gate_for(payload)
    if not gate:
        return None
    if str(payload.get("result_stage") or payload.get("stage") or "").lower() in {"partial", "streaming"}:
        return None
    status = _structured_status(payload)
    if not status:
        # Keep this helper conservative: success_from_payload is still useful
        # for callers, but an unstructured payload must not journal progress.
        return None
    return gate, status


def _write_result(result: object) -> WriteResult:
    metadata = getattr(result, "metadata", None)
    if metadata is None:
        return WriteResult.unknown(changed=bool(getattr(result, "changed", False)))
    return WriteResult(
        changed=bool(getattr(result, "changed", False)),
        bytes_written=getattr(metadata, "bytes_written", None),
        files_written=tuple(getattr(metadata, "files_written", ()) or ()),
        replacements=int(getattr(metadata, "replacements", 0) or 0),
        appends=int(getattr(metadata, "appends", 0) or 0),
        fsync_publications=int(getattr(metadata, "fsync_publications", 0) or 0),
        known=bool(getattr(metadata, "known", getattr(metadata, "bytes_written", None) is not None)),
    )


def _provenance(context: ActiveContext, payload: Mapping[str, object]) -> dict[str, Any]:
    profile = profile_from_payload(payload)
    # Workspace identity is derived from the active context, never accepted
    # from the operation payload.  A caller may carry a stale or forged
    # workspace field, but it must not be able to rewrite the provenance used
    # by completion and cross-worktree checks.
    workspace = "ws-" + context.workspace_instance_id
    git: dict[str, str] = {"workspace_instance_id": workspace}
    if context.branch:
        git["branch"] = _text(context.branch, 240)
    if context.sha:
        git["commit"] = _text(context.sha, 64)
    return {
        "git": git,
        "writer_session_id": _safe_id(context.session_id, "unknown"),
        "model_family": profile.model_family,
        "model_source": profile.model_source,
        "model_verified": profile.model_verified,
        "origin": "implementation-progress",
        "intent": "progress-maintenance",
    }


def validation_transition(
    payload: Mapping[str, object],
    context: ActiveContext,
    lookup: ProgressLookup | None = None,
) -> ValidationTransition:
    parsed = structured_validation(payload)
    if parsed is None:
        return ValidationTransition(reason="not_structured_validation")
    lookup = lookup or cheap_lookup(context, payload)
    if not lookup.available or lookup.identity is None or lookup.identity.source != "state":
        return ValidationTransition(gate=parsed[0], status=parsed[1], reason="no_matching_active_state")
    if is_red(_text(payload.get("output") or payload.get("stdout") or payload.get("stderr") or payload.get("result"), 800)):
        return ValidationTransition(gate=parsed[0], status=parsed[1], reason="red_result")
    store = lookup.store
    if store is None:
        return ValidationTransition(gate=parsed[0], status=parsed[1], reason="store_unavailable")
    gate, status = parsed
    try:
        state = store.read_state(lookup.identity.plan_id)
        if state is None or state.get("status") != "active":
            return ValidationTransition(gate=gate, status=status, reason="plan_not_active")
        validation = dict(state.get("validation") or {})
        previous_status = validation.get(gate, "")
        validation[gate] = status
        operation_material = {
            "project": context.project_id,
            "workspace": context.workspace_instance_id,
            "session": context.session_id,
            "plan": lookup.identity.plan_id,
            "gate": gate,
            "status": status,
            "previous": previous_status,
            "generation": state.get("generation", 0),
        }
        operation_id = "posttool-validation-" + hashlib.sha256(
            repr(sorted(operation_material.items())).encode("utf-8")
        ).hexdigest()[:40]
        result = store.record_event(
            lookup.identity.plan_id,
            kind="validation_changed",
            operation_id=operation_id,
            summary=f"Validation {gate}: {status}",
            evidence_codes=[f"{gate}_{status}"],
            state_update={"validation": validation},
            provenance=_provenance(context, payload),
        )
        return ValidationTransition(
            result=_write_result(result),
            gate=gate,
            status=status,
            changed=bool(result.changed),
            reason=result.reason or ("changed" if result.changed else "semantic_noop"),
        )
    except (CorruptRecordError, FutureSchemaError, IntegrityError, SchemaError, StoreError, OSError, ValueError):
        return ValidationTransition(gate=gate, status=status, reason="progress_state_unavailable")


def progress_checkpoint_reference(
    payload: Mapping[str, object], context: ActiveContext,
) -> dict[str, object] | None:
    """Return the only progress data allowed in a planned-work checkpoint."""

    lookup = cheap_lookup(context, payload)
    if not lookup.available or lookup.identity is None or lookup.identity.source != "state":
        return None
    if not _plan_is_approved(payload, lookup):
        return None
    semantic_hash = _text(getattr(lookup.identity, "semantic_hash", ""), 80)
    if not semantic_hash:
        return None
    return {
        "plan_id": lookup.identity.plan_id,
        "generation": lookup.identity.generation,
        "semantic_hash": semantic_hash,
    }


def _plan_is_approved(payload: Mapping[str, object], lookup: ProgressLookup) -> bool:
    if lookup.identity is None or lookup.store is None:
        return False
    plan_path = lookup.identity.plan_path
    for key in _PLAN_PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            plan_path = value.strip()
            break
    if plan_path:
        candidate = Path(plan_path).expanduser()
        if not candidate.is_absolute():
            candidate = lookup.store.paths.primary_root / candidate
        metadata = _safe_plan_metadata(candidate, lookup.store.paths.primary_root)
        if metadata is not None:
            # A present plan document is authoritative for approval. Missing
            # or pending metadata must not be upgraded merely because a
            # payload supplied a plan ID.
            return is_plan_approved(metadata)
    # A payload boolean or an explicit store plan ID is only a request.  It is
    # never approval evidence: completion and planned checkpoints require the
    # canonical plan document to be present and marked approved.
    return False


def _plan_identity_matches(payload: Mapping[str, object], lookup: ProgressLookup) -> bool:
    if lookup.identity is None or lookup.store is None:
        return False
    explicit_id = _value(payload, *_PLAN_KEYS)
    if isinstance(explicit_id, str) and explicit_id.strip() and explicit_id.strip() != lookup.identity.plan_id:
        return False
    for key in _PLAN_PATH_KEYS:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = lookup.store.paths.primary_root / candidate
        try:
            relative = candidate.absolute().relative_to(lookup.store.paths.primary_root).as_posix()
        except (OSError, ValueError):
            return False
        if _safe_plan_metadata(candidate, lookup.store.paths.primary_root) is None:
            return False
        expected = lookup.identity.plan_path
        if expected and relative != expected:
            return False
    return True


def _progress_hint(payload: Mapping[str, object]) -> bool:
    if any(isinstance(payload.get(key), str) and str(payload.get(key)).strip() for key in (*_PLAN_KEYS, *_PLAN_PATH_KEYS)):
        return True
    return any(isinstance(payload.get(key), bool) and payload.get(key) for key in _COMPLETION_KEYS)


def completion_requested(payload: Mapping[str, object]) -> bool:
    for key in _COMPLETION_KEYS:
        value = payload.get(key)
        if isinstance(value, bool) and value:
            return True
    nested = payload.get("completion")
    if isinstance(nested, Mapping):
        for key in ("complete", "verified", "status"):
            value = nested.get(key)
            if value is True or (isinstance(value, str) and value.lower() in {"complete", "completed", "verified", "pass"}):
                return True
    return False


def _workspace_matches(state: Mapping[str, object], context: ActiveContext, payload: Mapping[str, object]) -> bool:
    value = state.get("git")
    git = value if isinstance(value, Mapping) else {}
    recorded = str(git.get("workspace_instance_id") or "").strip()
    # The active cwd/worktree is the identity boundary.  Payload workspace
    # fields are advisory and must not redirect completion to another
    # worktree's state.
    expected = context.workspace_instance_id
    return not recorded or recorded in {expected, f"ws-{expected}"}


def _commit_matches(state: Mapping[str, object], context: ActiveContext) -> bool:
    value = state.get("git")
    git = value if isinstance(value, Mapping) else {}
    recorded = str(git.get("commit") or "").strip()
    current = str(context.sha or "").strip()
    if not recorded:
        return True
    if not current:
        return False
    return recorded.startswith(current) or current.startswith(recorded)


def _branch_matches(state: Mapping[str, object], context: ActiveContext) -> bool:
    value = state.get("git")
    git = value if isinstance(value, Mapping) else {}
    recorded = str(git.get("branch") or "").strip()
    if not recorded:
        return True
    if not context.branch:
        return False
    return recorded == context.branch


def _validation_ready(state: Mapping[str, object], payload: Mapping[str, object]) -> bool:
    validation = state.get("validation")
    if isinstance(validation, Mapping) and validation:
        return all(str(value).lower() == "pass" for value in validation.values())
    explicit = payload.get("validation_status") or payload.get("validationStatus")
    if isinstance(explicit, str) and explicit.lower() == "pass":
        return True
    return any(payload.get(key) is True for key in ("tests_passed", "build_passed", "lint_passed", "validation_passed"))


def _terminal_fingerprint(state: Mapping[str, object], context: ActiveContext) -> str:
    material = {
        "plan": state.get("plan_id", ""),
        "generation": state.get("generation", 0),
        "semantic_hash": state.get("semantic_hash", ""),
        "commit": context.sha,
        "branch": context.branch,
        "validation": state.get("validation", {}),
    }
    return hashlib.sha256(repr(sorted(material.items())).encode("utf-8")).hexdigest()


def complete_progress(
    payload: Mapping[str, object],
    context: ActiveContext,
    *,
    lookup: ProgressLookup | None = None,
) -> CompletionTransition:
    if not completion_requested(payload):
        return CompletionTransition(reason="completion_not_requested")
    lookup = lookup or cheap_lookup(context, payload)
    if not lookup.available or lookup.identity is None or lookup.identity.source != "state":
        if lookup.resolution.reason == "future_schema" and _progress_hint(payload):
            return CompletionTransition(
                in_scope=True,
                error_code="progress_future_schema",
                error_reason="active progress state uses an unsupported future schema",
                reason="future_schema",
            )
        if lookup.resolution.reason == "state_invalid" and _progress_hint(payload):
            return CompletionTransition(
                in_scope=True,
                error_code="progress_state_corrupt",
                error_reason="active progress state failed integrity verification",
                reason="state_invalid",
            )
        return CompletionTransition(in_scope=_progress_hint(payload), reason="no_matching_active_state")
    if not _plan_identity_matches(payload, lookup):
        return CompletionTransition(
            in_scope=True,
            error_code="progress_identity_mismatch",
            error_reason="active progress identity does not match the requested plan",
            reason="plan_identity_mismatch",
        )
    if not _plan_is_approved(payload, lookup):
        return CompletionTransition(in_scope=True, error_code="progress_approval_invalid", error_reason="active progress plan approval could not be verified", reason="approval_invalid")
    store = lookup.store
    if store is None:
        return CompletionTransition(in_scope=True, error_code="progress_store_unavailable", error_reason="active progress state is unavailable", reason="store_unavailable")
    try:
        # One bounded state read establishes completion evidence. The canonical
        # reader verifies the state cursor and journal hash chain internally;
        # the cursor is enough to distinguish the registration event from
        # later material progress. The store performs the locked recheck before
        # publication.
        state = store.read_state(lookup.identity.plan_id)
        if state is None or state.get("status") != "active":
            return CompletionTransition(in_scope=True, reason="plan_not_active")
        if state.get("origin") != "implementation-progress" or state.get("intent") != "progress-maintenance":
            return CompletionTransition(in_scope=True, error_code="progress_provenance_invalid", error_reason="active progress provenance could not be verified", reason="provenance_invalid")
        if not _workspace_matches(state, context, payload) or not _branch_matches(state, context) or not _commit_matches(state, context):
            return CompletionTransition(in_scope=True, error_code="progress_identity_mismatch", error_reason="active progress identity does not match the current workspace", reason="identity_mismatch")
        if int(state.get("last_event_sequence", 0) or 0) <= 1 and int(state.get("generation", 0) or 0) <= 1:
            return CompletionTransition(in_scope=True, error_code="progress_material_missing", error_reason="active progress has no material implementation evidence", reason="material_missing")
        if not _validation_ready(state, payload):
            return CompletionTransition(in_scope=True, error_code="progress_validation_incomplete", error_reason="required progress validation gates are not passing", reason="validation_incomplete")
        fingerprint = _terminal_fingerprint(state, context)
        result = store.record_event(
            lookup.identity.plan_id,
            kind="completed",
            operation_id="stop-progress-completed-" + fingerprint[:40],
            summary="Implementation progress completed",
            evidence_codes=["progress_completion_verified"],
            state_update={"status": "completed"},
            provenance=_provenance(context, payload),
        )
        return CompletionTransition(
            result=_write_result(result),
            changed=bool(result.changed),
            in_scope=True,
            reason=result.reason or ("completed" if result.changed else "semantic_noop"),
        )
    except FutureSchemaError:
        return CompletionTransition(in_scope=True, error_code="progress_future_schema", error_reason="active progress state uses an unsupported future schema", reason="future_schema")
    except (CorruptRecordError, IntegrityError, SchemaError):
        return CompletionTransition(in_scope=True, error_code="progress_state_corrupt", error_reason="active progress state failed integrity verification", reason="state_corrupt")
    except (StoreError, OSError, ValueError):
        return CompletionTransition(in_scope=True, error_code="progress_store_error", error_reason="active progress state could not be updated", reason="store_error")


__all__ = [
    "CompletionTransition",
    "ValidationTransition",
    "complete_progress",
    "completion_requested",
    "progress_checkpoint_reference",
    "structured_validation",
    "validation_transition",
]
