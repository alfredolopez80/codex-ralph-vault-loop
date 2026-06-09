#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

try:
    from .context_common import compact_json_loads, parse_timestamp, preview, read_tail_text, write_output
except ImportError:  # pragma: no cover - direct script execution
    from context_common import compact_json_loads, parse_timestamp, preview, read_tail_text, write_output


DEFAULT_INTERESTING_RE = re.compile(r"(?i)\b(error|warning|warn|failed|failure|exception|fallback)\b")
TIME_KEYS = ("timestamp", "time", "created_at", "date", "ts")
MESSAGE_KEYS = ("message", "msg", "error", "event", "text")


def line_record(path: Path, number: int, line: str, *, line_scope: str = "file") -> dict[str, Any]:
    parsed = compact_json_loads(line)
    if parsed:
        timestamp = next((parse_timestamp(parsed.get(key)) for key in TIME_KEYS if parsed.get(key) is not None), None)
        message = next((parsed.get(key) for key in MESSAGE_KEYS if parsed.get(key) is not None), line)
    else:
        timestamp = parse_timestamp(line)
        message = line
    return {
        "path": str(path),
        "line": number,
        "line_scope": line_scope,
        "timestamp": timestamp,
        "message": preview(message, limit=320),
        "raw": preview(line, limit=320),
    }


def load_records(paths: list[Path]) -> tuple[list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []
    truncated = False
    for path in paths:
        text, was_truncated = read_tail_text(path)
        truncated = truncated or was_truncated
        line_scope = "tail-relative" if was_truncated else "file"
        records.extend(line_record(path, index, line, line_scope=line_scope) for index, line in enumerate(text.splitlines(), start=1))
    return records, truncated


def matches(record: dict[str, Any], keywords: list[str], regex: re.Pattern[str] | None) -> bool:
    text = f"{record['message']} {record['raw']}"
    if keywords and any(keyword.lower() in text.lower() for keyword in keywords):
        return True
    if regex and regex.search(text):
        return True
    if not keywords and regex is None and DEFAULT_INTERESTING_RE.search(text):
        return True
    return False


def compact(paths: list[Path], hours: int | None, keywords: list[str], regex_text: str | None, limit: int) -> dict[str, Any]:
    records, truncated = load_records(paths)
    regex = re.compile(regex_text) if regex_text else None
    timestamped = [record for record in records if record["timestamp"] is not None]
    anchor = max((record["timestamp"] for record in timestamped), default=None)
    candidates = records
    mode = "recent-tail"
    if hours is not None and anchor is not None:
        cutoff = anchor - timedelta(hours=hours)
        candidates = [record for record in records if record["timestamp"] is not None and record["timestamp"] >= cutoff]
        mode = "timestamp-window"
    selected = [record for record in candidates if matches(record, keywords, regex)]
    if not selected and mode == "recent-tail":
        selected = candidates[-limit:]
    return {
        "files": [str(path) for path in paths],
        "mode": mode,
        "input_truncated": truncated,
        "time_anchor": anchor.isoformat() if anchor else None,
        "selected": selected[-limit:],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Compact Logs",
        "",
        f"- Files: `{len(report['files'])}`",
        f"- Mode: `{report['mode']}`",
        f"- Input truncated: `{'yes' if report['input_truncated'] else 'no'}`",
        f"- Time anchor: `{report['time_anchor'] or 'none'}`",
        "",
        "## Selected Lines",
    ]
    if not report["selected"]:
        lines.append("- none")
    for item in report["selected"]:
        timestamp = item["timestamp"].isoformat() if item["timestamp"] else "none"
        line_ref = f"tail+{item['line']}" if item.get("line_scope") == "tail-relative" else str(item["line"])
        lines.append(f"- `{item['path']}:{line_ref}` `{timestamp}` {item['message']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compact plain-text or JSONL logs into bounded, privacy-safe highlights.")
    parser.add_argument("files", nargs="+", help="Log files to compact.")
    parser.add_argument("--hours", type=int, help="Keep entries within this many hours of the newest parsed timestamp.")
    parser.add_argument("--keyword", action="append", default=[], help="Keyword to retain. Repeat for multiple keywords.")
    parser.add_argument("--regex", help="Regex used to retain matching log lines.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum selected lines to emit.")
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    args = parser.parse_args(argv)

    report = compact([Path(value).expanduser() for value in args.files], args.hours, args.keyword, args.regex, args.limit)
    write_output(render_markdown(report), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
