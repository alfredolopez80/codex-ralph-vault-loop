#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _gate_common import render_markdown, summarize


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a gates JSON report as Markdown.")
    parser.add_argument("report", nargs="?", default=".ralph-codex/reports/gates/latest.json")
    args = parser.parse_args()

    path = Path(args.report)
    report = json.loads(path.read_text(encoding="utf-8"))
    report["summary"] = summarize(report.get("results", []))
    print(render_markdown(report), end="")
    return 1 if report["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
