#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from context_common import preview, read_text_bounded, redact_structure, write_output


def type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def value_size(value: Any) -> int | None:
    if isinstance(value, (dict, list, str)):
        return len(value)
    return None


def walk(value: Any, path: str, depth: int, max_depth: int, max_items: int, rows: list[dict[str, Any]]) -> None:
    if len(rows) >= max_items:
        return
    rows.append({"path": path, "type": type_name(value), "size": value_size(value)})
    if depth >= max_depth:
        return
    if isinstance(value, dict):
        for key in sorted(value.keys(), key=str)[:max_items]:
            walk(value[key], f"{path}.{key}", depth + 1, max_depth, max_items, rows)
            if len(rows) >= max_items:
                return
    elif isinstance(value, list):
        for index, item in enumerate(value[:max_items]):
            walk(item, f"{path}[{index}]", depth + 1, max_depth, max_items, rows)
            if len(rows) >= max_items:
                return


def parse_json_or_jsonl(path: Path) -> tuple[Any, bool]:
    text, truncated = read_text_bounded(path)
    try:
        return json.loads(text), truncated
    except json.JSONDecodeError:
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows, truncated


def summarize(path: Path, max_items: int, max_depth: int, include_samples: bool) -> dict[str, Any]:
    value, truncated = parse_json_or_jsonl(path)
    rows: list[dict[str, Any]] = []
    walk(value, "$", 0, max_depth, max_items, rows)
    top_keys = sorted(value.keys(), key=str)[:max_items] if isinstance(value, dict) else []
    report: dict[str, Any] = {
        "path": str(path),
        "file_size_bytes": path.stat().st_size,
        "input_truncated": truncated,
        "root_type": type_name(value),
        "root_size": value_size(value),
        "top_level_keys": [str(key) for key in top_keys],
        "sample_paths": rows,
    }
    if include_samples and isinstance(value, dict):
        report["top_level_samples"] = {
            str(key): preview(value[key], limit=160)
            for key in top_keys
            if not isinstance(value[key], (dict, list))
        }
    elif include_samples and isinstance(value, list):
        report["top_level_samples"] = redact_structure(value[: min(max_items, 5)], limit=160)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# JSON Summary",
        "",
        f"- Path: `{report['path']}`",
        f"- File size bytes: `{report['file_size_bytes']}`",
        f"- Input truncated: `{'yes' if report['input_truncated'] else 'no'}`",
        f"- Root type: `{report['root_type']}`",
        f"- Root size: `{report['root_size']}`",
        "",
        "## Top-Level Keys",
    ]
    lines.extend(f"- `{key}`" for key in report["top_level_keys"]) if report["top_level_keys"] else lines.append("- none")
    lines.extend(["", "## Sample Paths"])
    for row in report["sample_paths"]:
        size = "n/a" if row["size"] is None else str(row["size"])
        lines.append(f"- `{row['path']}` type=`{row['type']}` size=`{size}`")
    if "top_level_samples" in report:
        lines.extend(["", "## Top-Level Samples"])
        samples = report["top_level_samples"]
        if isinstance(samples, dict):
            lines.extend(f"- `{key}`: {value}" for key, value in samples.items())
        else:
            lines.append(preview(samples, limit=500))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize JSON or JSONL structure without dumping full content.")
    parser.add_argument("path", help="JSON or JSONL file to summarize.")
    parser.add_argument("--max-items", type=int, default=20, help="Maximum keys, list items, and sample paths to inspect.")
    parser.add_argument("--max-depth", type=int, default=4, help="Maximum nested depth for sample paths.")
    parser.add_argument("--samples", action="store_true", help="Include bounded top-level scalar samples.")
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    args = parser.parse_args(argv)

    report = summarize(Path(args.path).expanduser(), args.max_items, args.max_depth, args.samples)
    write_output(render_markdown(report), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
