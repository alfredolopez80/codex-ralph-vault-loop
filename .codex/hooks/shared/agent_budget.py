"""Bounded, content-free budgets for native workers and advisors.

The router decides whether delegation has value; this module only supplies
the conservative accounting primitives used at the spawn boundary.  It does
not read configuration, start processes, or persist prompt/response content.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import time
from typing import Any, Mapping

from .redaction import is_red
from .runtime_profile import classify_model


SCHEMA_VERSION = 1
MAX_THREADS = 2
MAX_DEPTH = 1
MAX_TASK_JOBS = 2
MAX_TASK_ADVISORS = 1
MAX_PACKET_BYTES = 4_096
MAX_RESULT_BYTES = 4_096
MAX_REASON_CODES = 8
MAX_FAILURE_FINGERPRINTS = 8
MAX_TIMESTAMPS = 8


@dataclass(frozen=True)
class BudgetDecision:
    """A pure answer to the question "may this child start now?"."""

    allowed: bool
    reason: str
    remaining_jobs: int
    remaining_advisors: int


def _bounded_text(value: object, limit: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _hash(value: object) -> str:
    return sha256(str(value).encode("utf-8")).hexdigest()[:24]


def _safe_code(value: object, *, prefix: str) -> str:
    """Keep reason/fingerprint fields as codes, never arbitrary content."""
    text = _bounded_text(value, 96).lower()
    if text and re.fullmatch(r"[a-z0-9_.:-]+", text):
        return text
    return f"{prefix}-{_hash(text)}" if text else ""


def task_signature(payload: Mapping[str, object], *, prompt: str = "") -> str:
    """Create a deterministic task identity without retaining raw text.

    The prompt contributes only an ephemeral digest.  Identity fields are
    intentionally bounded and sanitized so this value is safe for ledgers,
    reports, and test fixtures.
    """

    model = _bounded_text(payload.get("model") or payload.get("model_name"), 96)
    branch = _bounded_text(payload.get("branch") or payload.get("git_branch"), 160)
    workspace = _bounded_text(
        payload.get("workspace_identity") or payload.get("workspace") or payload.get("cwd"),
        240,
    )
    project = _bounded_text(payload.get("project_id") or payload.get("project"), 160)
    intent = _bounded_text(payload.get("intent") or payload.get("task_type"), 96).lower()
    sensitivity = _bounded_text(
        payload.get("sensitivity") or payload.get("classification") or payload.get("sensitivity_class"),
        32,
    ).upper()
    if not sensitivity and prompt and is_red(prompt):
        sensitivity = "RED"
    checkpoint = _bounded_text(
        payload.get("checkpoint_identity") or payload.get("checkpoint_hash"),
        96,
    )
    prompt_hash = _hash(" ".join(prompt.split()).lower()) if prompt else _bounded_text(payload.get("prompt_hash"), 96)
    material = {
        "project": project,
        "workspace": workspace,
        "branch": branch,
        "prompt_hash": prompt_hash,
        "intent": intent,
        "sensitivity": sensitivity,
        "model_family": classify_model(model),
        "checkpoint": checkpoint,
        "session": _bounded_text(payload.get("session_id") or payload.get("sessionId"), 96),
    }
    return _hash(json.dumps(material, sort_keys=True, separators=(",", ":")))


def _ints(value: object, *, default: int = 0, maximum: int = 2**31 - 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(parsed, maximum))


def normalize_ledger(
    value: Mapping[str, object] | None = None,
    *,
    signature: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Return a bounded ledger, recovering malformed fields conservatively."""

    source = dict(value or {})
    timestamp = float(time.time() if now is None else now)
    reasons = source.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = []
    failure_fingerprints = source.get("failure_fingerprints", [])
    if not isinstance(failure_fingerprints, list):
        failure_fingerprints = []
    timestamps = source.get("timestamps", [])
    if not isinstance(timestamps, list):
        timestamps = []
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "task_signature": _bounded_text(source.get("task_signature") or signature, 96),
        "max_threads": MAX_THREADS,
        "max_depth": MAX_DEPTH,
        "agents_started": _ints(source.get("agents_started"), maximum=MAX_TASK_JOBS),
        "advisors_started": _ints(source.get("advisors_started"), maximum=MAX_TASK_ADVISORS),
        "workers_started": _ints(source.get("workers_started"), maximum=MAX_TASK_JOBS),
        "worker_reserved_jobs": _ints(source.get("worker_reserved_jobs"), maximum=MAX_TASK_JOBS),
        "reserved_jobs": _ints(source.get("reserved_jobs"), maximum=MAX_TASK_JOBS),
        "reasons": [
            _safe_code(reason, prefix="reason")
            for reason in reasons
            if _safe_code(reason, prefix="reason")
        ][-MAX_REASON_CODES:],
        "failure_fingerprints": [
            _safe_code(fingerprint, prefix="failure")
            for fingerprint in failure_fingerprints
            if _safe_code(fingerprint, prefix="failure")
        ][-MAX_FAILURE_FINGERPRINTS:],
        "bytes_sent": _ints(source.get("bytes_sent"), maximum=MAX_PACKET_BYTES * MAX_TASK_JOBS),
        "bytes_received": _ints(source.get("bytes_received"), maximum=MAX_RESULT_BYTES * MAX_TASK_JOBS),
        "timestamps": [
            _bounded_text(item, 48)
            for item in timestamps
            if _bounded_text(item, 48)
        ][-MAX_TIMESTAMPS:],
        "updated_at": _bounded_text(source.get("updated_at"), 48),
    }
    if not normalized["updated_at"]:
        normalized["updated_at"] = str(timestamp)
    normalized["agents_started"] = min(
        normalized["agents_started"], normalized["max_threads"], normalized["max_depth"] + MAX_TASK_JOBS - 1
    )
    normalized["reserved_jobs"] = min(
        max(normalized["reserved_jobs"], normalized["worker_reserved_jobs"]),
        max(0, normalized["max_threads"] - normalized["agents_started"]),
    )
    return normalized


def budget_decision(
    ledger: Mapping[str, object] | None,
    *,
    kind: str,
    sensitivity: str = "GREEN",
    executor_model: str = "",
    depth: int = 0,
    independent: bool = False,
    critical_review: bool = False,
    failure_fingerprints: tuple[str, ...] = (),
) -> BudgetDecision:
    """Evaluate a spawn request with fail-closed optional delegation."""

    state = normalize_ledger(ledger)
    normalized_kind = _bounded_text(kind, 32).lower()
    sensitivity = _bounded_text(sensitivity, 16).upper() or "GREEN"
    if sensitivity == "RED":
        return BudgetDecision(False, "red-local-only", 0, 0)
    if _ints(depth) >= MAX_DEPTH:
        return BudgetDecision(False, "max-depth-reached", 0, max(0, MAX_TASK_ADVISORS - state["advisors_started"]))
    if normalized_kind not in {"worker", "advisor"}:
        return BudgetDecision(False, "unknown-delegation-kind", 0, 0)
    if classify_model(executor_model) == "sol" and normalized_kind == "advisor" and not critical_review:
        return BudgetDecision(False, "sol-self-supervision-suppressed", 0, 0)
    distinct_failures = {fingerprint for fingerprint in failure_fingerprints if fingerprint}
    previous_failures = set(state["failure_fingerprints"])
    if (distinct_failures or previous_failures) and len(previous_failures | distinct_failures) < 2:
        return BudgetDecision(False, "inspect-first-failure-locally", 0, max(0, MAX_TASK_ADVISORS - state["advisors_started"]))
    used = state["agents_started"] + state["reserved_jobs"]
    remaining_jobs = max(0, MAX_TASK_JOBS - used)
    remaining_advisors = max(0, MAX_TASK_ADVISORS - state["advisors_started"])
    if remaining_jobs <= 0:
        return BudgetDecision(False, "task-job-budget-exhausted", 0, remaining_advisors)
    if normalized_kind == "advisor" and remaining_advisors <= 0:
        return BudgetDecision(False, "advisor-budget-exhausted", remaining_jobs, 0)
    if not independent and normalized_kind == "worker":
        return BudgetDecision(False, "independent-block-required", remaining_jobs, remaining_advisors)
    return BudgetDecision(True, "budget-available", remaining_jobs, remaining_advisors)


def record_spawn(
    ledger: Mapping[str, object] | None,
    *,
    kind: str,
    reason: str,
    bytes_sent: int = 0,
    bytes_received: int = 0,
    timestamp: str = "",
    signature: str = "",
) -> dict[str, Any]:
    """Record bounded metadata after a validated start/completion event."""

    state = normalize_ledger(ledger, signature=signature)
    normalized_kind = _bounded_text(kind, 32).lower()
    if state["agents_started"] < MAX_TASK_JOBS:
        state["agents_started"] += 1
    if normalized_kind == "advisor":
        state["advisors_started"] = min(MAX_TASK_ADVISORS, state["advisors_started"] + 1)
    elif normalized_kind == "worker":
        state["workers_started"] = min(MAX_TASK_JOBS, state["workers_started"] + 1)
        state["worker_reserved_jobs"] = max(0, state["worker_reserved_jobs"] - 1)
    state["reserved_jobs"] = max(0, state["reserved_jobs"] - 1)
    if reason:
        safe_reason = _safe_code(reason, prefix="reason")
        if safe_reason:
            state["reasons"] = (state["reasons"] + [safe_reason])[-MAX_REASON_CODES:]
    state["bytes_sent"] = min(MAX_PACKET_BYTES * MAX_TASK_JOBS, state["bytes_sent"] + _ints(bytes_sent))
    state["bytes_received"] = min(
        MAX_RESULT_BYTES * MAX_TASK_JOBS,
        state["bytes_received"] + _ints(bytes_received),
    )
    if timestamp:
        state["timestamps"] = (state["timestamps"] + [_bounded_text(timestamp, 48)])[-MAX_TIMESTAMPS:]
    return state


def record_result(
    ledger: Mapping[str, object] | None,
    *,
    bytes_received: int = 0,
    timestamp: str = "",
    signature: str = "",
) -> dict[str, Any]:
    """Record only bounded completion metadata; the result body is discarded."""

    state = normalize_ledger(ledger, signature=signature)
    state["bytes_received"] = min(
        MAX_RESULT_BYTES * MAX_TASK_JOBS,
        state["bytes_received"] + _ints(bytes_received),
    )
    if timestamp:
        state["timestamps"] = (state["timestamps"] + [_bounded_text(timestamp, 48)])[-MAX_TIMESTAMPS:]
    return state


def record_failure(ledger: Mapping[str, object] | None, fingerprint: str, *, signature: str = "") -> dict[str, Any]:
    state = normalize_ledger(ledger, signature=signature)
    bounded = _safe_code(fingerprint, prefix="failure")
    if bounded and bounded not in state["failure_fingerprints"]:
        state["failure_fingerprints"] = (state["failure_fingerprints"] + [bounded])[-MAX_FAILURE_FINGERPRINTS:]
    return state


def bounded_packet(
    *,
    question: str,
    context: str,
    files: list[str] | tuple[str, ...] = (),
    constraints: str = "",
    output_format: str = "Verdict; Evidence; Risks; Recommendation; Uncertainty",
    budget_bytes: int = MAX_PACKET_BYTES,
) -> dict[str, Any]:
    """Build a sanitized advisor packet whose serialized size is hard-capped."""

    limit = max(256, min(MAX_PACKET_BYTES, _ints(budget_bytes, default=MAX_PACKET_BYTES)))
    packet = {
        "question": "[redacted-local-only]" if is_red(question) else _bounded_text(question, 800),
        "context": "[redacted-local-only]" if is_red(context) else _bounded_text(context, 1_600),
        "files": [_bounded_text(path, 180) for path in files if _bounded_text(path, 180)][:12],
        "constraints": "[redacted-local-only]" if is_red(constraints) else _bounded_text(constraints, 800),
        "output_format": _bounded_text(output_format, 240),
        "budget_bytes": limit,
    }
    def encoded_size() -> int:
        return len(json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    if encoded_size() <= limit:
        return packet

    # Preserve the packet schema while shrinking every free-text field. A
    # caller-controlled question is just as untrusted and unbounded as the
    # context, so truncating only context would not enforce the hard cap.
    packet["files"] = packet["files"][:4]
    packet["context"] = packet["context"][: max(0, limit // 3)]
    packet["constraints"] = packet["constraints"][: max(0, limit // 6)]
    packet["question"] = packet["question"][: max(0, limit // 4)]
    while encoded_size() > limit:
        candidates = [
            key for key in ("question", "context", "constraints", "output_format")
            if isinstance(packet[key], str) and packet[key]
        ]
        if packet["files"]:
            packet["files"] = packet["files"][: max(0, len(packet["files"]) // 2)]
        elif candidates:
            key = max(candidates, key=lambda item: len(str(packet[item])))
            value = str(packet[key])
            packet[key] = value[: max(0, len(value) // 2)]
        else:
            # Keep a final guard if the packet schema grows in the future.
            packet["question"] = ""
            packet["context"] = ""
            packet["constraints"] = ""
            packet["output_format"] = ""
            packet["files"] = []
            break
    return packet


def packet_bytes(packet: Mapping[str, object]) -> int:
    return len(json.dumps(dict(packet), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"))


__all__ = [
    "BudgetDecision",
    "MAX_DEPTH",
    "MAX_PACKET_BYTES",
    "MAX_RESULT_BYTES",
    "MAX_TASK_ADVISORS",
    "MAX_TASK_JOBS",
    "MAX_THREADS",
    "SCHEMA_VERSION",
    "bounded_packet",
    "budget_decision",
    "normalize_ledger",
    "packet_bytes",
    "record_failure",
    "record_result",
    "record_spawn",
    "task_signature",
]
