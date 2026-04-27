#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _eval_common import load_json, load_scorecard, score_run, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Score one run against a scorecard.")
    parser.add_argument("--scorecard", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    scorecard = load_scorecard(Path(args.scorecard))
    payload = load_json(Path(args.metrics))
    metrics = payload.get("metrics", payload)
    hard_gates = payload.get("hard_gates", payload)
    result = score_run(scorecard, metrics, hard_gates)
    if args.output:
        write_json(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if not result["hard_gates"]["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
