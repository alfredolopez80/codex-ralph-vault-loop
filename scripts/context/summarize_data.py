#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

try:
    from .context_common import preview, write_output
except ImportError:  # pragma: no cover - direct script execution
    from context_common import preview, write_output


def detect_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".tsv":
        return "tsv"
    return "csv"


def read_rows(path: Path, limit_rows: int) -> tuple[str, list[dict[str, Any]], bool]:
    kind = detect_kind(path)
    rows: list[dict[str, Any]] = []
    truncated = False
    if kind == "jsonl":
        with path.open(encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= limit_rows:
                    truncated = True
                    break
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    value = {"_raw": line.strip()}
                rows.append(value if isinstance(value, dict) else {"value": value})
        return kind, rows, truncated
    delimiter = "\t" if kind == "tsv" else ","
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        for index, row in enumerate(reader):
            if index >= limit_rows:
                truncated = True
                break
            rows.append(dict(row))
    return kind, rows, truncated


def summarize(path: Path, limit_rows: int, sample: int) -> dict[str, Any]:
    kind, rows, truncated = read_rows(path, limit_rows)
    columns = sorted({str(key) for row in rows for key in row.keys()})
    empty_counts = {
        column: sum(1 for row in rows if row.get(column) in {None, ""})
        for column in columns
    }
    sample_rows = [
        {column: preview(row.get(column, ""), limit=120) for column in columns}
        for row in rows[:sample]
    ]
    return {
        "path": str(path),
        "kind": kind,
        "file_size_bytes": path.stat().st_size,
        "rows_scanned": len(rows),
        "row_count_estimate": f">={limit_rows}" if truncated else str(len(rows)),
        "input_truncated": truncated,
        "columns": columns,
        "empty_counts": empty_counts,
        "sample_rows": sample_rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Data Summary",
        "",
        f"- Path: `{report['path']}`",
        f"- Kind: `{report['kind']}`",
        f"- File size bytes: `{report['file_size_bytes']}`",
        f"- Rows scanned: `{report['rows_scanned']}`",
        f"- Row count estimate: `{report['row_count_estimate']}`",
        f"- Input truncated: `{'yes' if report['input_truncated'] else 'no'}`",
        "",
        "## Columns",
    ]
    lines.extend(f"- `{column}` empty=`{report['empty_counts'][column]}`" for column in report["columns"]) if report["columns"] else lines.append("- none")
    lines.extend(["", "## Sample Rows"])
    if not report["sample_rows"]:
        lines.append("- none")
    for index, row in enumerate(report["sample_rows"], start=1):
        rendered = ", ".join(f"{key}={value}" for key, value in row.items())
        lines.append(f"- `{index}` {rendered}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize CSV, TSV, or JSONL files with bounded samples.")
    parser.add_argument("path", help="CSV, TSV, or JSONL file to summarize.")
    parser.add_argument("--limit-rows", type=int, default=1000, help="Maximum rows to scan.")
    parser.add_argument("--sample", type=int, default=20, help="Maximum sample rows to emit.")
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    args = parser.parse_args(argv)

    report = summarize(Path(args.path).expanduser(), args.limit_rows, args.sample)
    write_output(render_markdown(report), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
