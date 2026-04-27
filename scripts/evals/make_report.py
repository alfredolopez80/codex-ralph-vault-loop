#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _eval_common import load_json


def render(report: dict) -> str:
    lines = [
        "# Evaluation Report",
        "",
        f"Scorecard: {report.get('scorecard', 'unknown')}",
        f"Score: {report.get('score', 0)}",
        f"Hard gates: {'PASS' if report.get('hard_gates', {}).get('passed') else 'FAIL'}",
        "",
        "## Category Scores",
        "",
    ]
    for category, score in report.get("category_scores", {}).items():
        lines.append(f"- `{category}`: {score}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a scored eval JSON file as Markdown.")
    parser.add_argument("score")
    parser.add_argument("--output")
    args = parser.parse_args()

    report = load_json(Path(args.score))
    markdown = render(report)
    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
