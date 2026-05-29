#!/usr/bin/env python3
from __future__ import annotations

from shared.paths import append_jsonl, ensure_runtime, now_iso, read_hook_input
from shared.redaction import is_red


ROUTE_MARKER = "ROUTE_DECISION"


def _message(payload: dict) -> str:
    value = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
    return value if isinstance(value, str) else ""


def _count(payload: dict, *keys: str) -> int:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return len(value)
    return 0


def has_route_decision(payload: dict, message: str) -> bool:
    if payload.get("route_decision") or payload.get("routeDecision"):
        return True
    return ROUTE_MARKER in message


def is_nontrivial(payload: dict, message: str) -> bool:
    if payload.get("route_decision_not_required") or payload.get("routeDecisionNotRequired"):
        return False
    if str(payload.get("sensitivity", "")).upper() == "RED":
        return False
    if _count(payload, "tool_call_count", "toolCallCount", "tool_calls", "toolCalls") >= 3:
        return True
    if _count(payload, "turn_count", "turnCount", "messages") >= 5:
        return True
    duration = payload.get("duration_seconds") or payload.get("durationSeconds") or 0
    if isinstance(duration, (int, float)) and duration >= 30:
        return True
    return len(message) >= 1200


def main() -> int:
    payload = read_hook_input()
    if payload.get("stop_hook_active"):
        return 0

    message = _message(payload)
    if not message or is_red(message):
        return 0
    if not is_nontrivial(payload, message) or has_route_decision(payload, message):
        return 0

    root = ensure_runtime()
    warning = {
        "created_at": now_iso(),
        "event": "StopRouteDecisionWarn",
        "severity": "warn",
        "reason": "Non-trivial session completed without a visible ROUTE_DECISION marker.",
    }
    append_jsonl(root / "cost" / "routing-warnings.jsonl", warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
