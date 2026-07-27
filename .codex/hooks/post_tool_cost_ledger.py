#!/usr/bin/env python3
from __future__ import annotations

from shared.cost_policy import (
    estimate_context_units,
    measured_output,
    output_contains,
    route_family,
    source_scope,
    tool_family,
    tool_name,
)
from shared.paths import append_jsonl, ensure_runtime, now_iso, read_hook_input


def main() -> int:
    try:
        payload = read_hook_input()
        tool = tool_name(payload)
        output_chars, output_truncated = measured_output(payload)
        root = ensure_runtime()
        append_jsonl(
            root / "cost" / "tool-ledger.jsonl",
            {
                "created_at": now_iso(),
                "event": str(payload.get("hook_event_name") or "PostToolUse"),
                "hook_role": "post_tool_cost_ledger",
                "source_scope": source_scope(),
                "duplicate_suppressed": False,
                "tool": tool,
                "tool_family": tool_family(tool),
                "route_family": route_family(tool),
                "route_decision_observed": output_contains(payload, "ROUTE_DECISION"),
                "approval_relay_observed": output_contains(payload, "APPROVAL_NEEDED"),
                "output_chars": output_chars,
                "output_truncated": output_truncated,
                "estimated_context_units": estimate_context_units(output_chars),
                "estimated_cost_units": estimate_context_units(output_chars),
                "subscription_usage_measured": False,
                "success": bool(payload.get("success", True)),
            },
        )
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
