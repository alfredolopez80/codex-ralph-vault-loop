#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from _cost_common import route_task


def main() -> int:
    parser = argparse.ArgumentParser(description="Route a task through the Ralph cost/model policy.")
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--complexity", required=True, type=int)
    parser.add_argument("--sensitivity", required=True)
    args = parser.parse_args()

    route = route_task(args.task_type, args.complexity, args.sensitivity)
    print(json.dumps(route, indent=2, sort_keys=True))
    return 1 if route["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
