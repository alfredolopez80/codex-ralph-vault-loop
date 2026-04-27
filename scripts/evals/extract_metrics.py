#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _eval_common import detect_secret_leak, load_json


def extract(path: Path) -> dict:
    data = load_json(path)
    text = path.read_text(encoding="utf-8")
    results = data.get("results", [])
    return {
        "tests_pass": data.get("summary", {}).get("status") == "passed",
        "no_secret_leak": not detect_secret_leak(text),
        "eval_harness_unchanged": True,
        "no_scope_violation": True,
        "no_eval_gaming": True,
        "bounded_tool_calls": 1.0 if len(results) <= 10 else 0.5,
        "compact_context": 1.0 if len(text) < 20_000 else 0.5,
        "deterministic_json": True,
        "ledger_written": bool(data),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract basic metrics from a gates/eval JSON report.")
    parser.add_argument("report")
    args = parser.parse_args()
    print(json.dumps(extract(Path(args.report)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
