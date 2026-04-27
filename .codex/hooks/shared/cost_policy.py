from __future__ import annotations


def estimate_cost_units(payload: dict) -> int:
    text = str(payload)
    return max(1, len(text) // 1_000)


def tool_name(payload: dict) -> str:
    value = payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "unknown"
    return str(value)
