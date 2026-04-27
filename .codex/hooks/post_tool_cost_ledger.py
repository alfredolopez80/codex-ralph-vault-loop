#!/usr/bin/env python3
from __future__ import annotations

from shared.cost_policy import estimate_cost_units, tool_name
from shared.paths import append_jsonl, ensure_runtime, now_iso, read_hook_input


def main() -> int:
    payload = read_hook_input()
    root = ensure_runtime()
    append_jsonl(
        root / "cost" / "tool-ledger.jsonl",
        {
            "created_at": now_iso(),
            "event": "PostToolUse",
            "tool": tool_name(payload),
            "estimated_cost_units": estimate_cost_units(payload),
            "success": bool(payload.get("success", True)),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
