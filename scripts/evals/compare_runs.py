#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _eval_common import load_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two scored eval runs.")
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    args = parser.parse_args()

    baseline = load_json(Path(args.baseline))
    candidate = load_json(Path(args.candidate))
    delta = float(candidate.get("score", 0.0)) - float(baseline.get("score", 0.0))
    output = {
        "baseline": args.baseline,
        "candidate": args.candidate,
        "baseline_score": baseline.get("score", 0.0),
        "candidate_score": candidate.get("score", 0.0),
        "delta": round(delta, 4),
        "regression": delta < 0,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 1 if output["regression"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
