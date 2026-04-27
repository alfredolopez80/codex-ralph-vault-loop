#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _eval_common import REPORT_DIR, REPO_ROOT, load_json, load_scorecard, now_iso, score_run, write_json


TOY_FIXTURE = REPO_ROOT / "tests" / "evals" / "fixtures" / "autoresearch_toy_speed"
TOY_SCORECARD = REPO_ROOT / "config" / "scorecards" / "ralph_autoresearch_v1.yaml"


def collect_gates_baseline(output: Path) -> int:
    completed = subprocess.run(
        [sys.executable, "scripts/gates/run-gates.py", "--minimal"],
        text=True,
        capture_output=True,
        check=False,
    )
    payload = {
        "created_at": now_iso(),
        "suite": "gates",
        "command": "python3 scripts/gates/run-gates.py --minimal",
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    write_json(output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return completed.returncode


def collect_toy_baseline(output: Path) -> int:
    scorecard = load_scorecard(TOY_SCORECARD)
    payload = load_json(TOY_FIXTURE / "baseline_metrics.json")
    result = score_run(scorecard, payload.get("metrics", payload), payload.get("hard_gates", payload))
    baseline = {
        "created_at": now_iso(),
        "suite": "toy",
        "fixture": str(TOY_FIXTURE.relative_to(REPO_ROOT)),
        "scorecard": scorecard["id"],
        "result": result,
    }
    write_json(output, baseline)
    print(json.dumps(baseline, indent=2, sort_keys=True))
    return 0 if result["hard_gates"]["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a baseline gates report for future eval comparison.")
    parser.add_argument("--suite", choices=("gates", "toy"), default="gates")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.suite == "toy":
        output = Path(args.output) if args.output else REPORT_DIR / "toy_baseline.json"
        return collect_toy_baseline(output)

    output = Path(args.output) if args.output else REPORT_DIR / "baseline.json"
    return collect_gates_baseline(output)


if __name__ == "__main__":
    raise SystemExit(main())
