#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from _gate_common import REPORT_DIR, detect_project, now_iso, summarize, write_reports


def run_json(command: list[str]) -> tuple[int, list[dict]]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if not completed.stdout.strip():
        return completed.returncode, [
            {
                "name": "gate-subcommand",
                "status": "failed",
                "command": command,
                "reason": "gate subcommand returned no JSON result",
                "stdout": "",
                "stderr": completed.stderr[-4_000:],
                "exit_code": completed.returncode,
            }
        ]
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return completed.returncode or 1, [
            {
                "name": "gate-subcommand",
                "status": "failed",
                "command": command,
                "reason": "gate subcommand returned malformed JSON",
                "stdout": completed.stdout[-4_000:],
                "stderr": completed.stderr[-4_000:],
                "exit_code": completed.returncode or 1,
            }
        ]
    results = payload.get("results", [])
    if not isinstance(results, list):
        return completed.returncode or 1, [
            {
                "name": "gate-subcommand",
                "status": "failed",
                "command": command,
                "reason": "gate subcommand JSON omitted a results list",
                "stdout": completed.stdout[-4_000:],
                "stderr": completed.stderr[-4_000:],
                "exit_code": completed.returncode or 1,
            }
        ]
    return completed.returncode, results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Ralph quality gates and write latest reports.")
    parser.add_argument("--minimal", action="store_true", help="Shortcut for --mode minimal.")
    parser.add_argument("--mode", choices=["minimal", "standard", "full", "critical"], default="standard")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    mode = "minimal" if args.minimal else args.mode
    project = detect_project()
    results: list[dict] = []

    _, test_results = run_json([sys.executable, "scripts/gates/run-tests.py", "--mode", mode])
    results.extend(test_results)
    _, security_results = run_json([sys.executable, "scripts/gates/run-security.py", "--mode", mode, *(["--strict"] if args.strict else [])])
    results.extend(security_results)

    report = {
        "created_at": now_iso(),
        "mode": mode,
        "strict": bool(args.strict or mode == "critical"),
        "project": project,
        "results": results,
        "summary": summarize(results),
    }
    json_path, md_path = write_reports(report, REPORT_DIR)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": report["summary"]}, indent=2, sort_keys=True))
    return 1 if report["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
