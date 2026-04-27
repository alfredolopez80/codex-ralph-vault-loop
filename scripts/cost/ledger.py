#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from _cost_common import append_ledger, route_task


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a routing decision to the Ralph cost ledger.")
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--complexity", required=True, type=int)
    parser.add_argument("--sensitivity", required=True)
    parser.add_argument("--status", default="planned")
    args = parser.parse_args()

    decision = route_task(args.task_type, args.complexity, args.sensitivity)
    path = append_ledger({"status": args.status, "decision": decision})
    print(json.dumps({"ledger": str(path), "decision": decision}, indent=2, sort_keys=True))
    return 1 if decision["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
