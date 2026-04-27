#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _eval_common import REPORT_DIR, load_json, load_scorecard, score_run, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a scorecard against a metrics JSON fixture.")
    parser.add_argument("--scorecard", default="config/scorecards/cost_router_v1.yaml")
    parser.add_argument("--input", default=None, help="Metrics JSON. If omitted, uses a minimal passing fixture.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    scorecard = load_scorecard(Path(args.scorecard))
    if args.input:
        payload = load_json(Path(args.input))
    else:
        payload = {
            "metrics": {metric: 1.0 for metrics in scorecard["metrics"].values() for metric in metrics},
            "hard_gates": {gate: True for gate in scorecard["hard_gates"]},
        }
    result = score_run(scorecard, payload.get("metrics", payload), payload.get("hard_gates", payload))
    output = Path(args.output) if args.output else REPORT_DIR / f"{scorecard['id']}_latest.json"
    write_json(output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if not result["hard_gates"]["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
