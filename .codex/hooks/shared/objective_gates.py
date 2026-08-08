from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from file_line_guard import evaluate as evaluate_file_line
from implementation_notes_guard import GitMetadataError, ImplementationNotesError, evaluate as evaluate_implementation_notes

from .stop_scope import StopScope, evidence_fingerprint, state_is_fresh, state_matches_scope


@dataclass(frozen=True)
class GateFinding:
    code: str
    reason: str
    priority: int
    critical: bool = False
    source: str = "payload"
    fingerprint: str = ""


@dataclass(frozen=True)
class GateReports:
    reports: tuple[str, ...] = ()
    corrupt_states: tuple[str, ...] = ()


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _bool(payload: Mapping[str, object], *keys: str) -> bool | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
    return None


def _nonempty(value: object) -> bool:
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(_text(value))


def _finding(code: str, reason: str, *, priority: int, critical: bool = False, source: str = "payload", parts: Iterable[str] = ()) -> GateFinding:
    fingerprint = evidence_fingerprint([code, *parts])
    return GateFinding(code, reason, priority, critical, source, fingerprint)


def _state_value(state: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in state:
            return state[key]
    conditions = state.get("conditions")
    if isinstance(conditions, Mapping):
        for key in keys:
            if key in conditions:
                return conditions[key]
    return None


def _failed_signal(state: Mapping[str, object]) -> tuple[str, str] | None:
    checks = (
        ("quality_failed", ("quality_passed", "qualityPassed")),
        ("correctness_failed", ("correctness_passed", "correctnessPassed")),
        ("tests_failed", ("tests_passed", "testsPassed")),
        ("validation_failed", ("validation_status", "validationStatus")),
        ("build_failed", ("build_passed", "buildPassed")),
        ("lint_failed", ("lint_passed", "lintPassed")),
        ("typecheck_failed", ("typecheck_passed", "typecheckPassed")),
        ("implementation_incomplete", ("implementation_complete", "implementationComplete")),
        ("tests_not_executed", ("tests_executed", "testsExecuted")),
    )
    for code, keys in checks:
        value = _state_value(state, *keys)
        if value is False:
            return code, code.replace("_", " ")
        if code == "validation_failed" and str(value).lower() in {"fail", "failed", "error"}:
            return code, "validation failed"
    status = str(_state_value(state, "status", "result", "last_result") or "").lower()
    if status in {"failed", "failure", "error"}:
        return "objective_failed", "objective evidence reports a failure"
    return None


def _pending_signal(state: Mapping[str, object]) -> bool:
    status = str(_state_value(state, "status", "state") or "").lower()
    if status in {"pending", "in_progress", "in-progress", "active"}:
        return True
    for key in ("pending_tasks", "pendingTasks", "pending", "in_progress", "inProgress"):
        value = _state_value(state, key)
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, (int, float)) and value > 0:
            return True
    steps = _state_value(state, "steps")
    if isinstance(steps, list):
        return any(isinstance(item, Mapping) and str(item.get("status", "")).lower() in {"pending", "in_progress"} for item in steps)
    return False


def _loop_active(state: Mapping[str, object], path: Path | None) -> bool:
    kind = str(_state_value(state, "kind", "state_type", "stateType") or "").lower()
    is_loop = "loop" in kind or _state_value(state, "loop_active", "loopActive") is True
    if path is not None and "loop" in path.name.lower():
        is_loop = True
    if not is_loop or _state_verified(state):
        return False
    iteration = _state_value(state, "iteration")
    maximum = _state_value(state, "max_iterations", "maxIterations")
    return isinstance(iteration, int) and isinstance(maximum, int) and 0 <= iteration < maximum


def _state_verified(state: Mapping[str, object]) -> bool:
    value = _state_value(state, "verified_done", "verifiedDone")
    return value is True


def _candidate_state_paths(scope: StopScope) -> list[Path]:
    root = scope.context.workspace_root
    state_root = Path(os.environ.get("CODEX_HOOK_STATE_ROOT", str(root / ".codex" / "state"))).expanduser()
    paths: list[Path] = []
    session = scope.context.session_id
    for base in (state_root / session, root / ".ralph" / "state" / session, root / ".codex" / "state" / session):
        if not base.is_dir():
            continue
        try:
            paths.extend(sorted(path for path in base.glob("*.json") if path.is_file() and not path.is_symlink()))
        except OSError:
            continue
    for path in (root / ".ralph" / "plan-state.json", root / ".codex" / "plan-state.json", root / "plan-state.json"):
        if path.is_file() and not path.is_symlink():
            paths.append(path)
    return paths


def _implementation_notes_candidate(payload: Mapping[str, object], scope: StopScope) -> bool:
    """Check whether this Stop has an implementation-notes plan in scope.

    The full evaluator resolves canonical worktree topology and performs many
    bounded Git lookups. It is only applicable when a plan is named, linked in
    the message, or marked for this session by the plan workflow. Skipping it
    otherwise preserves the old evaluator's behavior (it never discovers
    unrelated plans) while keeping the normal Stop path fast.
    """
    for key in (
        "implementation_plan_path",
        "implementationPlanPath",
        "plan_path",
        "planPath",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    message = payload.get("last_assistant_message") or payload.get("lastAssistantMessage")
    if isinstance(message, str) and ".ralph/plans/" in message and ".md" in message:
        return True

    state_root = Path(
        os.environ.get("CODEX_HOOK_STATE_ROOT", str(scope.context.workspace_root / ".codex" / "state"))
    ).expanduser()
    marker = state_root / scope.context.session_id / "implementation-notes-plan.json"
    try:
        return marker.is_file() and not marker.is_symlink()
    except OSError:
        return False


def _state_entries(payload: Mapping[str, object], scope: StopScope) -> tuple[list[tuple[Mapping[str, object], Path | None]], list[str]]:
    entries: list[tuple[Mapping[str, object], Path | None]] = []
    reports: list[str] = []
    for key in ("objective_state", "quality_state", "plan_state", "checkpoint_state"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            entries.append((value, None))
    for path in _candidate_state_paths(scope):
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            reports.append(f"corrupt_state:{path.name}")
            continue
        if isinstance(data, dict):
            entries.append((data, path))
    return entries, reports


def collect_state_findings(payload: Mapping[str, object], scope: StopScope) -> tuple[list[GateFinding], GateReports]:
    findings: list[GateFinding] = []
    entries, reports = _state_entries(payload, scope)
    corrupt = tuple(item for item in reports if item.startswith("corrupt_state:"))
    for state, path in entries:
        matched, reason = state_matches_scope(state, scope)
        if not matched:
            reports.append(reason)
            continue
        if not state_is_fresh(state, path):
            reports.append("expired_state")
            continue
        failed = _failed_signal(state)
        if failed:
            code, label = failed
            findings.append(_finding(code, f"Objective gate failed: {label}. Resolve it and rerun the gate.", priority=10, critical=bool(state.get("critical")), source="state", parts=[str(state.get("evidence_fingerprint", ""))]))
            continue
        if _loop_active(state, path):
            findings.append(
                _finding(
                    "loop_active",
                    "Objective loop is still active without verified completion; finish the current iteration or verify done.",
                    priority=55,
                    source="state",
                    parts=[str(state.get("iteration", "")), str(state.get("max_iterations", ""))],
                )
            )
            continue
        if _state_verified(state):
            continue
        verified = _state_value(state, "verified_done", "verifiedDone")
        if verified is False:
            findings.append(
                _finding(
                    "verified_done_false",
                    "The current task is explicitly not verified done; complete its objective gate.",
                    priority=50,
                    source="state",
                    parts=[scope.task_signature, str(state.get("evidence_fingerprint", ""))],
                )
            )
            continue
        if _pending_signal(state):
            findings.append(_finding("objective_pending", "Objective state is still pending; complete the current task before stopping.", priority=60, source="state", parts=[str(state.get("status", ""))]))
    return findings, GateReports(tuple(reports), corrupt)


def collect_payload_findings(payload: Mapping[str, object], scope: StopScope) -> list[GateFinding]:
    findings: list[GateFinding] = []
    if _bool(payload, "file_line_failed", "fileLineFailed", "file_line_violation", "fileLineViolation") is True:
        findings.append(_finding("file_line_violation", "File-line hard gate failed; split the oversized file before stopping.", priority=5, critical=True))
    if _bool(payload, "safety_failure", "safetyFailed", "integrity_failure", "production_integrity_failed") is True:
        findings.append(_finding("safety_failure", "Safety or production integrity gate failed. Resolve it before stopping.", priority=0, critical=True, parts=[_text(payload.get("evidence_fingerprint"))]))

    if _bool(payload, "tests_failed", "testsFailed", "test_failed", "testFailed") is True:
        findings.append(_finding("tests_failed", "Objective tests failed. Fix the failing test and rerun it.", priority=20, critical=bool(payload.get("critical")), parts=[_text(payload.get("evidence_fingerprint")), _text(payload.get("test_command"))]))
    if _bool(payload, "lint_failed", "lintFailed", "typecheck_failed", "typecheckFailed", "build_failed", "buildFailed") is True:
        findings.append(_finding("validation_failed", "Required validation failed. Rerun the failing gate after fixing it.", priority=25, critical=bool(payload.get("critical")), parts=[_text(payload.get("evidence_fingerprint"))]))

    for key, code, reason in (
        ("required_files_missing", "required_file_missing", "A required file is missing; restore it before stopping."),
        ("missing_required_files", "required_file_missing", "A required file is missing; restore it before stopping."),
        ("pending_tasks", "objective_pending", "Objective tasks remain pending; complete them before stopping."),
    ):
        value = payload.get(key)
        if _nonempty(value):
            findings.append(_finding(code, reason, priority=40 if code == "objective_pending" else 15, critical=code == "required_file_missing", parts=[str(value)[:120]]))

    verified = _bool(payload, "verified_done", "verifiedDone")
    if verified is False and scope.task_identity_present:
        findings.append(_finding("verified_done_false", "The current task is explicitly not verified done; complete its objective gate.", priority=50, parts=[scope.task_signature]))
    return findings


def collect_file_line_finding(payload: Mapping[str, object]) -> GateFinding | None:
    try:
        response = evaluate_file_line(dict(payload), "Stop")
    except (OSError, ValueError):
        return None
    if not response:
        return None
    return _finding("file_line_violation", "File-line hard gate failed; split the oversized file before stopping.", priority=5, critical=True)


def collect_implementation_notes_finding(payload: Mapping[str, object], scope: StopScope) -> GateFinding | None:
    if not _implementation_notes_candidate(payload, scope):
        return None
    try:
        response = evaluate_implementation_notes(dict(payload))
    except (GitMetadataError, ImplementationNotesError):
        return None
    if not response:
        return None
    return _finding("implementation_notes_missing", "Required implementation notes are missing or invalid; complete them before stopping.", priority=8, critical=True)


def collect_hard_findings(payload: Mapping[str, object], scope: StopScope) -> tuple[list[GateFinding], GateReports]:
    findings: list[GateFinding] = []
    file_line = collect_file_line_finding(payload)
    if file_line:
        findings.append(file_line)
    notes = collect_implementation_notes_finding(payload, scope)
    if notes:
        findings.append(notes)
    findings.extend(collect_payload_findings(payload, scope))
    state_findings, reports = collect_state_findings(payload, scope)
    findings.extend(state_findings)
    unique: dict[str, GateFinding] = {}
    for finding in findings:
        unique.setdefault(finding.code, finding)
    return list(unique.values()), reports


def route_report_codes(payload: Mapping[str, object]) -> list[str]:
    message = payload.get("last_assistant_message") or payload.get("lastAssistantMessage")
    if not isinstance(message, str) or not message.strip():
        return []
    if payload.get("route_decision") or payload.get("routeDecision") or "ROUTE_DECISION" in message:
        return []
    if payload.get("route_decision_not_required") or payload.get("routeDecisionNotRequired"):
        return []
    count = payload.get("tool_call_count") or payload.get("toolCallCount") or 0
    turns = payload.get("turn_count") or payload.get("turnCount") or 0
    duration = payload.get("duration_seconds") or payload.get("durationSeconds") or 0
    nontrivial = (isinstance(count, (int, float)) and count >= 3) or (isinstance(turns, (int, float)) and turns >= 5) or (isinstance(duration, (int, float)) and duration >= 30) or len(message) >= 1200
    return ["route_marker_missing"] if nontrivial else []


def phrase_report_codes(payload: Mapping[str, object]) -> list[str]:
    message = payload.get("last_assistant_message") or payload.get("lastAssistantMessage")
    if not isinstance(message, str):
        return []
    phrases = ("probably", "assuming", "seems complete", "should work", "good enough", "no further action is needed")
    lowered = message.lower()
    return ["rationalization_phrase_seen"] if any(phrase in lowered for phrase in phrases) else []
