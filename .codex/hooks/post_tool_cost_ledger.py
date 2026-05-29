#!/usr/bin/env python3
from __future__ import annotations

from shared.cost_policy import estimate_cost_units, output_contains, route_family, tool_name
from shared.paths import append_jsonl, ensure_runtime, now_iso, read_hook_input


def main() -> int:
    try:
        payload = read_hook_input()
        tool = tool_name(payload)
        root = ensure_runtime()
        append_jsonl(
            root / "cost" / "tool-ledger.jsonl",
            {
                "created_at": now_iso(),
                "event": "PostToolUse",
                "tool": tool,
                "route_family": route_family(tool),
                "route_decision_observed": output_contains(payload, "ROUTE_DECISION"),
                "approval_relay_observed": output_contains(payload, "APPROVAL_NEEDED"),
                "estimated_cost_units": estimate_cost_units(payload),
                "success": bool(payload.get("success", True)),
            },
        )
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
