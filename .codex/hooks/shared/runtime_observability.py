"""Privacy-safe runtime observability for Ralph hook events.

The writer is deliberately boring: it accepts a small allow-list of scalar
metrics, hashes identities, and appends bounded JSONL below the approved Ralph
runtime.  It never stores prompt, response, tool, memory, or path content.
The values named ``estimated_context_units`` are a documented local heuristic
and are not token, credit, or subscription measurements.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from typing import Any, Mapping

from .active_context import ActiveContext
from .cost_policy import estimate_context_units, measured_output, source_scope
from .runtime_profile import MODEL_SOURCES, profile_from_payload
from .runtime_event_store import append_normalized, event_path


SCHEMA_VERSION = 1
SCHEMA_NAME = "ralph_runtime_overhead"
EVENTS = {
    "session_start",
    "user_prompt",
    "pre_tool",
    "post_tool",
    "stop",
    "subagent",
    "maintenance",
}
INTERACTIVE_EVENTS = EVENTS - {"maintenance"}
MAX_EVENT_BYTES = 16 * 1024
PROJECT_ID_RE = re.compile(r"^p-[a-f0-9]{16}$")
SAFE_CODE_RE = re.compile(r"^[a-z0-9_.:-]{1,96}$")
SCOPE_VALUES = {"project", "global", "suppressed-global"}

# These names are intentionally not accepted by normalize_event.  The check
# also protects future callers from accidentally widening the event payload.
PRIVACY_DENYLIST = {
    "prompt",
    "raw_prompt",
    "assistant_response",
    "response",
    "tool_body",
    "tool_input",
    "tool_response",
    "memory_body",
    "memory",
    "transcript",
    "api_key",
    "secret",
    "credential",
    "wallet",
    "customer_data",
    "path",
    "workspace_root",
}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _timestamp(value: object) -> str:
    text = _text(value, 48)
    if text and re.fullmatch(r"[0-9T:+.Z-]{1,48}", text):
        return text
    return _now_iso()


def _bounded_int(value: object, *, maximum: int = 2**31 - 1) -> int:
    try:
        return max(0, min(int(value), maximum))
    except (TypeError, ValueError):
        return 0


def _bounded_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _text(value: object, limit: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _digest(value: object, *, prefix: str = "id") -> str:
    if value is None:
        return ""
    text = _text(value, 512)
    if not text:
        return ""
    if re.fullmatch(rf"{re.escape(prefix)}-[a-f0-9]{{24}}", text):
        return text
    return f"{prefix}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:24]}"


def _code(value: object, *, prefix: str = "code") -> str:
    text = _text(value, 96).lower()
    if SAFE_CODE_RE.fullmatch(text):
        return text
    return _digest(text, prefix=prefix) if text else ""


def _codes(value: object, *, prefix: str = "code", limit: int = 16) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for item in values:
        code = _code(item, prefix=prefix)
        if code and code not in result:
            result.append(code)
        if len(result) >= limit:
            break
    return result


def _payload_value(payload: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def _project_id(context: ActiveContext | None, event: Mapping[str, object]) -> str:
    value = context.project_id if context is not None else event.get("project_id")
    text = _text(value, 64)
    if PROJECT_ID_RE.fullmatch(text):
        return text
    # An event without a valid project identity is not written.  Returning an
    # empty value lets append_event fail open without creating an unsafe path.
    return ""


def estimated_context_for_payload(payload: Mapping[str, object]) -> int:
    """Estimate visible context from bounded output material, not tokens."""
    measured, _truncated = measured_output(dict(payload))
    return estimate_context_units(measured)


def task_signature_for_payload(payload: Mapping[str, object]) -> str:
    """Return only a digest; the prompt is used ephemerally by agent_budget."""
    try:
        from .agent_budget import task_signature

        prompt = _payload_value(payload, "prompt", "user_prompt")
        return task_signature(payload, prompt=prompt if isinstance(prompt, str) else "")
    except Exception:
        material = json.dumps(
            {
                "project": _text(payload.get("project_id") or payload.get("project")),
                "branch": _text(payload.get("branch") or payload.get("git_branch")),
                "intent": _text(payload.get("intent") or payload.get("task_type")),
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def normalize_event(event: Mapping[str, object]) -> dict[str, Any] | None:
    """Normalize an event to the versioned, content-free schema.

    Unknown fields are dropped.  Denylisted fields are never copied, even if a
    caller accidentally supplies them.  Invalid event names or project IDs are
    rejected instead of being represented as zero-valued metrics.
    """
    if not isinstance(event, Mapping):
        return None
    if any(key in event for key in PRIVACY_DENYLIST):
        # A caller may include a raw field alongside valid metrics; fail closed
        # for that record rather than risk a future schema widening.
        return None
    name = _code(event.get("event"), prefix="event")
    if name not in EVENTS:
        return None
    project_id = _project_id(None, event)
    if not project_id:
        return None
    profile = _code(event.get("profile"), prefix="profile") or "conservative_unknown"
    family = _code(event.get("model_family"), prefix="model") or "unknown"
    source_candidate = _text(event.get("model_source"), 32).lower()
    model_source = source_candidate if source_candidate in MODEL_SOURCES else "unknown"
    model_verified = _bounded_bool(event.get("model_verified"))
    output_bytes = _bounded_int(event.get("output_bytes"), maximum=MAX_EVENT_BYTES)
    context_units = event.get("estimated_context_units")
    if context_units is None:
        context_units = estimate_context_units(output_bytes)
    scope = event.get("source_scope")
    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "schema_name": SCHEMA_NAME,
        "timestamp": _timestamp(event.get("timestamp")),
        "monotonic_duration_ns": _bounded_int(event.get("monotonic_duration_ns"), maximum=10**15),
        "session_id": _digest(event.get("session_id"), prefix="session") or "unknown",
        "turn_id": _digest(event.get("turn_id"), prefix="turn") or "unknown",
        "task_signature": _digest(event.get("task_signature"), prefix="task") or "unknown",
        "project_id": project_id,
        "event": name,
        "dispatcher": _code(event.get("dispatcher"), prefix="dispatcher") or "unknown",
        "profile": profile,
        "model_family": family,
        "model_source": model_source,
        "model_verified": model_verified if model_verified is not None else False,
        "tool_family": _code(event.get("tool_family"), prefix="tool") or "none",
        "components_considered": _codes(event.get("components_considered"), prefix="component"),
        "components_executed": _codes(event.get("components_executed"), prefix="component"),
        "components_skipped": _codes(event.get("components_skipped"), prefix="component"),
        "skipped_reason": _codes(event.get("skipped_reason"), prefix="skip"),
        "process_count": _bounded_int(event.get("process_count"), maximum=128),
        "child_process_count": _bounded_int(event.get("child_process_count"), maximum=128),
        "output_bytes": output_bytes,
        "estimated_context_units": _bounded_int(context_units, maximum=MAX_EVENT_BYTES),
        "persistence_bytes": _bounded_int(event.get("persistence_bytes"), maximum=32 * 1024 * 1024),
        "block_reason_code": _codes(event.get("block_reason_code"), prefix="block", limit=8),
        "continuation_count": _bounded_int(event.get("continuation_count"), maximum=32),
        "advisor_count": _bounded_int(event.get("advisor_count"), maximum=32),
        "cache_hit": _bounded_bool(event.get("cache_hit")),
        "success": _bounded_bool(event.get("success")),
        "source_scope": scope if isinstance(scope, str) and scope in SCOPE_VALUES else "project",
        "duplicate_suppressed": bool(event.get("duplicate_suppressed", False)),
        "subscription_usage_measured": False,
        "scenario": _code(event.get("scenario"), prefix="scenario") or "unspecified",
        "maintenance_deferred": bool(event.get("maintenance_deferred", name == "maintenance")),
    }
    # Keep optional confidence and provenance labels enumerable.
    confidence = _code(event.get("confidence"), prefix="confidence")
    if confidence:
        normalized["confidence"] = confidence
    if bool(event.get("user_supplied_usage", False)):
        normalized["user_supplied_usage"] = True
    return normalized


def build_event(
    *,
    context: ActiveContext | None,
    payload: Mapping[str, object] | None,
    event: str,
    dispatcher: str,
    started_ns: int | None = None,
    duration_ns: int | None = None,
    **metrics: object,
) -> dict[str, Any] | None:
    """Build a normalized event from a hook payload without retaining it."""
    payload = payload or {}
    profile = profile_from_payload(payload)
    output_bytes = metrics.get("output_bytes")
    if output_bytes is None:
        output_bytes = estimated_context_for_payload(payload)
        # estimated_context_for_payload returns units; output is unknown here.
        output_bytes = 0
    session = _payload_value(payload, "session_id", "sessionId") or (context.session_id if context else "")
    turn = _payload_value(payload, "turn_id", "turnId", "conversation_turn_id")
    project_id = context.project_id if context else _text(payload.get("project_id"), 64)
    model_source = metrics.pop("model_source", None)
    model_verified = metrics.pop("model_verified", None)
    source = metrics.pop("source_scope", None) or source_scope()
    event_payload: dict[str, object] = {
        "project_id": project_id,
        "event": event,
        "dispatcher": dispatcher,
        "session_id": session,
        "turn_id": turn,
        "task_signature": metrics.pop("task_signature", None) or task_signature_for_payload(payload),
        "profile": metrics.pop("profile", None) or profile.name,
        "model_family": metrics.pop("model_family", None) or profile.model_family,
        "model_source": model_source or profile.model_source,
        "model_verified": profile.model_verified if model_verified is None else model_verified,
        "source_scope": source,
        "monotonic_duration_ns": duration_ns
        if duration_ns is not None
        else max(0, time.perf_counter_ns() - started_ns) if started_ns is not None else 0,
        **metrics,
    }
    if "output_bytes" not in event_payload:
        event_payload["output_bytes"] = 0
    if "estimated_context_units" not in event_payload:
        event_payload["estimated_context_units"] = estimate_context_units(_bounded_int(output_bytes))
    return normalize_event(event_payload)


def append_event(context: ActiveContext | None, event: Mapping[str, object]) -> bool:
    """Append one event atomically; all local runtime errors fail open."""
    normalized = normalize_event(event)
    if normalized is None:
        return False
    return append_normalized(_project_id(context, normalized), normalized, max_event_bytes=MAX_EVENT_BYTES)


def record_event(
    context: ActiveContext | None,
    payload: Mapping[str, object] | None,
    *,
    event: str,
    dispatcher: str,
    started_ns: int | None = None,
    duration_ns: int | None = None,
    **metrics: object,
) -> bool:
    normalized = build_event(
        context=context,
        payload=payload,
        event=event,
        dispatcher=dispatcher,
        started_ns=started_ns,
        duration_ns=duration_ns,
        **metrics,
    )
    return append_event(context, normalized or {})


__all__ = [
    "EVENTS",
    "INTERACTIVE_EVENTS",
    "MAX_EVENT_BYTES",
    "PRIVACY_DENYLIST",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "append_event",
    "build_event",
    "estimated_context_for_payload",
    "event_path",
    "normalize_event",
    "record_event",
    "task_signature_for_payload",
]
