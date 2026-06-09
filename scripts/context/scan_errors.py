#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from .context_common import preview, read_tail_text, write_output
except ImportError:  # pragma: no cover - direct script execution
    from context_common import preview, read_tail_text, write_output


DEFAULT_PATTERN = r"(?i)\b(error|warning|warn|failed|failure|exception|traceback|panic)\b"


def normalize_message(line: str) -> str:
    text = re.sub(r"\b\d+\b", "<n>", preview(line, limit=220))
    text = re.sub(r"\s+", " ", text).strip()
    return text or "<blank>"


def scan_file(path: Path, pattern: re.Pattern[str], context_lines: int) -> list[dict[str, Any]]:
    text, truncated = read_tail_text(path)
    lines = text.splitlines()
    matches: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not pattern.search(line):
            continue
        start = max(0, index - context_lines)
        end = min(len(lines), index + context_lines + 1)
        matches.append(
            {
                "path": str(path),
                "line": index + 1,
                "message": normalize_message(line),
                "context": [preview(item) for item in lines[start:end]],
                "truncated_input": truncated,
            }
        )
    return matches


def summarize(paths: list[Path], limit: int, context_lines: int, pattern_text: str) -> dict[str, Any]:
    pattern = re.compile(pattern_text)
    all_matches: list[dict[str, Any]] = []
    for path in paths:
        all_matches.extend(scan_file(path, pattern, context_lines))
    counts = Counter(match["message"] for match in all_matches)
    first_by_message: dict[str, dict[str, Any]] = {}
    for match in all_matches:
        first_by_message.setdefault(match["message"], match)
    top = [
        {
            "count": count,
            "message": message,
            "first": first_by_message[message],
        }
        for message, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]
    return {"files": [str(path) for path in paths], "match_count": len(all_matches), "top": top}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Error Scan",
        "",
        f"- Files: `{len(report['files'])}`",
        f"- Matches: `{report['match_count']}`",
        "",
        "## Top Findings",
    ]
    if not report["top"]:
        lines.append("- none")
    for item in report["top"]:
        first = item["first"]
        lines.extend(
            [
                f"- Count `{item['count']}`: {item['message']}",
                f"  - First seen: `{first['path']}:{first['line']}`",
                f"  - Input truncated: `{'yes' if first['truncated_input'] else 'no'}`",
                "  - Context:",
            ]
        )
        lines.extend(f"    - {line}" for line in first["context"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract compact error and warning summaries from log or text files.")
    parser.add_argument("files", nargs="+", help="Log or text files to scan.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum grouped findings to emit.")
    parser.add_argument("--context-lines", type=int, default=2, help="Surrounding lines to include around the first match.")
    parser.add_argument("--pattern", default=DEFAULT_PATTERN, help="Regex used to select error or warning lines.")
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    args = parser.parse_args(argv)

    report = summarize([Path(value).expanduser() for value in args.files], args.limit, args.context_lines, args.pattern)
    write_output(render_markdown(report), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
