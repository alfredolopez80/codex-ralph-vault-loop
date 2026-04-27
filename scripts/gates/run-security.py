#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from _gate_common import detect_project, result, run_command


def main() -> int:
    parser = argparse.ArgumentParser(description="Run optional security gates.")
    parser.add_argument("--mode", choices=["minimal", "standard", "full", "critical"], default="standard")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    project = detect_project()
    strict = args.strict or args.mode == "critical"
    security = project["security"]
    results = []

    if args.mode == "minimal":
        results.append(result("security", "skipped", reason="minimal mode"))
    else:
        if security["gitleaks"]:
            results.append(run_command("security.gitleaks", ["gitleaks", "detect", "--no-banner", "--redact"], timeout=180))
        else:
            results.append(result("security.gitleaks", "failed" if strict else "skipped", reason="gitleaks not installed"))
        if security["semgrep"]:
            results.append(run_command("security.semgrep", ["semgrep", "--config", "auto", "."], timeout=240))
        else:
            results.append(result("security.semgrep", "failed" if strict else "skipped", reason="semgrep not installed"))

    print(json.dumps({"results": results}, indent=2, sort_keys=True))
    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
