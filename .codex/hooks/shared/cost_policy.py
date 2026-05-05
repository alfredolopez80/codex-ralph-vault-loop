from __future__ import annotations


def estimate_cost_units(payload: dict) -> int:
    text = str(payload)
    return max(1, len(text) // 1_000)


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


def output_contains(payload: dict, marker: str) -> bool:
    for key in ("output", "stdout", "stderr", "result", "message"):
        value = payload.get(key)
        if isinstance(value, str) and marker in value:
            return True
    return False
