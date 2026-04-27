#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _eval_common import REPORT_DIR, now_iso, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a baseline gates report for future eval comparison.")
    parser.add_argument("--output", default=str(REPORT_DIR / "baseline.json"))
    args = parser.parse_args()

    completed = subprocess.run([sys.executable, "scripts/gates/run-gates.py", "--minimal"], text=True, capture_output=True, check=False)
    payload = {
        "created_at": now_iso(),
        "command": "python3 scripts/gates/run-gates.py --minimal",
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
