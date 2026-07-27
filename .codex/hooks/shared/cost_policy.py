from __future__ import annotations

import os
from typing import Any


MAX_MEASURED_OUTPUT_CHARS = 12_000
OUTPUT_FIELDS = ("output", "stdout", "stderr", "result", "message")


def estimate_context_units(characters: int) -> int:
    """Return a transparent local approximation, never subscription usage."""
    return max(0, (max(0, characters) + 3) // 4)


def _bounded_value_length(value: Any, remaining: int) -> tuple[int, bool]:
    if remaining <= 0:
        return 0, value not in (None, "", [], {})
    if isinstance(value, (str, bytes)):
        return min(len(value), remaining), len(value) > remaining
    if isinstance(value, dict):
        values = value.values()
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        text = str(value)
        return min(len(text), remaining), len(text) > remaining

    used = 0
    truncated = False
    for item in values:
        size, item_truncated = _bounded_value_length(item, remaining - used)
        used += size
        truncated = truncated or item_truncated
        if used >= remaining:
            break
    return used, truncated


def measured_output(payload: dict[str, Any]) -> tuple[int, bool]:
    """Measure bounded response material without persisting its content."""
    values = [payload.get(field) for field in OUTPUT_FIELDS if field in payload]
    for field in ("tool_response", "toolResponse"):
        response = payload.get(field)
        if isinstance(response, dict):
            values.extend(response.get(name) for name in OUTPUT_FIELDS if name in response)
    used = 0
    truncated = False
    for value in values:
        size, value_truncated = _bounded_value_length(value, MAX_MEASURED_OUTPUT_CHARS - used)
        used += size
        truncated = truncated or value_truncated
        if used >= MAX_MEASURED_OUTPUT_CHARS:
            break
    return used, truncated


def source_scope() -> str:
    return "global" if os.environ.get("RALPH_HOOK_SCOPE") == "global" else "project"


def tool_name(payload: dict) -> str:
    value = payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "unknown"
    return str(value)


def route_family(tool: str) -> str:
    normalized = tool.lower()
    if "minimax_agentic_fast" in normalized or "minimax_coding_tools" in normalized:
        return "mcp:minimax-fast"
    if "zai_coding_deep" in normalized:
        return "mcp:zai-deep"
    if "zai_coding_fast" in normalized or "zai_" in normalized or "zread" in normalized:
        return "mcp:zai-fast"
    if "spawn_agent" in normalized or "wait_agent" in normalized or "send_input" in normalized:
        return "codex-subagent"
    if "route-task" in normalized or "ledger.py" in normalized:
        return "local"
    return "local"


def tool_family(tool: str) -> str:
    normalized = tool.lower()
    if any(marker in normalized for marker in ("exec", "shell", "command", "terminal")):
        return "command"
    if any(marker in normalized for marker in ("apply_patch", "write", "edit")):
        return "file_write"
    if any(marker in normalized for marker in ("read", "rg", "search", "find")):
        return "file_read"
    if "agent" in normalized:
        return "agent"
    return "other"


def output_contains(payload: dict, marker: str) -> bool:
    for key in ("output", "stdout", "stderr", "result", "message"):
        value = payload.get(key)
        if isinstance(value, str) and marker in value:
            return True
    return False
