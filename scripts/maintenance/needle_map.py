#!/usr/bin/env python3
"""Small, bounded repository and artifact maps for context-efficient inspection."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_DIR = REPO_ROOT / "scripts" / "security"
if str(SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(SECURITY_DIR))

from sensitive_content import redact_text as redact_sensitive_text  # noqa: E402


SKIP_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ralph-codex",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
BINARY_SUFFIXES = {
    ".7z",
    ".avif",
    ".db",
    ".dmg",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".sqlite",
    ".tar",
    ".tgz",
    ".webp",
    ".zip",
}
TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".log", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
DEFAULT_MAX_BYTES = 6000
DEFAULT_MAX_FILES = 300
DEFAULT_MAX_MATCHES = 30


def is_binary_like(path: Path) -> bool:
    return path.suffix.lower() in BINARY_SUFFIXES


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts) or is_binary_like(path)


def iter_files(root: Path, max_files: int = DEFAULT_MAX_FILES) -> list[Path]:
    files: list[Path] = []
    root = root.resolve()
    for current, dir_names, file_names in os.walk(root):
        current_path = Path(current)
        dir_names[:] = sorted(name for name in dir_names if not should_skip(current_path / name))
        for name in sorted(file_names):
            if len(files) >= max_files:
                return files
            path = current_path / name
            if should_skip(path):
                continue
            files.append(path)
    return files


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_limited(path: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[str, bool]:
    with path.open("rb") as handle:
        data = handle.read(max(0, max_bytes + 1))
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace"), truncated


def safe_preview(text: str, limit: int = 240) -> str:
    redacted, _changed = redact_sensitive_text(text)
    return redacted.strip()[:limit]


def repo_map(root: Path, max_files: int = DEFAULT_MAX_FILES) -> dict[str, Any]:
    files = iter_files(root, max_files=max_files)
    by_dir: dict[str, int] = defaultdict(int)
    by_suffix: Counter[str] = Counter()
    for path in files:
        relative = path.relative_to(root)
        by_dir[relative.parts[0] if len(relative.parts) > 1 else "."] += 1
        by_suffix[path.suffix.lower() or "<none>"] += 1
    return {
        "mode": "repo",
        "root": str(root),
        "file_count_sampled": len(files),
        "truncated": len(files) >= max_files,
        "top_dirs": dict(sorted(by_dir.items(), key=lambda item: (-item[1], item[0]))[:20]),
        "suffixes": dict(sorted(by_suffix.items(), key=lambda item: (-item[1], item[0]))[:20]),
        "sample_files": [rel(path, root) for path in files[:50]],
    }


def line_matches(text: str, pattern: re.Pattern[str], max_matches: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            matches.append({"line": number, "preview": safe_preview(line)})
        if len(matches) >= max_matches:
            break
    return matches


def log_map(root: Path, needle: str, max_files: int, max_bytes: int, max_matches: int) -> dict[str, Any]:
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    results = []
    for path in iter_files(root, max_files=max_files):
        if path.suffix.lower() not in {".log", ".jsonl", ".txt", ".md"}:
            continue
        text, truncated = read_limited(path, max_bytes=max_bytes)
        matches = line_matches(text, pattern, max_matches)
        if matches:
            results.append({"path": rel(path, root), "truncated": truncated, "matches": matches})
        if len(results) >= max_matches:
            break
    return {"mode": "logs", "needle": needle, "results": results, "result_count": len(results)}


def json_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(str(key) for key in list(value.keys())[:40])}
    if isinstance(value, list):
        return {"type": "array", "length_sampled": len(value), "first": json_shape(value[0]) if value else None}
    return {"type": type(value).__name__}


def json_map(path: Path, needle: str, max_bytes: int) -> dict[str, Any]:
    text, truncated = read_limited(path, max_bytes=max_bytes)
    try:
        parsed = json.loads(text)
        shape = json_shape(parsed)
    except json.JSONDecodeError:
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(rows) >= 20:
                break
        shape = {"type": "jsonl", "rows_sampled": len(rows), "first": json_shape(rows[0]) if rows else None}
    payload = {"mode": "json", "path": str(path), "truncated": truncated, "shape": shape}
    if needle:
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
        payload["matches"] = line_matches(text, pattern, DEFAULT_MAX_MATCHES)
    return payload


def csv_map(path: Path, needle: str, max_bytes: int, max_matches: int) -> dict[str, Any]:
    text, truncated = read_limited(path, max_bytes=max_bytes)
    sample = list(csv.DictReader(text.splitlines()))[:20]
    columns = list(sample[0].keys()) if sample else []
    payload: dict[str, Any] = {
        "mode": "csv",
        "path": str(path),
        "truncated": truncated,
        "columns": columns,
        "rows_sampled": len(sample),
    }
    if needle:
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
        payload["matches"] = line_matches(text, pattern, max_matches)
    return payload


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).expanduser().resolve()
    if args.mode == "repo":
        return repo_map(root, max_files=args.max_files)
    if args.mode == "logs":
        if not args.needle:
            raise SystemExit("--needle is required for logs mode")
        return log_map(root, args.needle, args.max_files, args.max_bytes, args.max_matches)
    path = Path(args.path or args.root).expanduser().resolve()
    if should_skip(path):
        raise SystemExit(f"refusing skipped or binary-like path: {path}")
    if args.mode == "json":
        return json_map(path, args.needle or "", args.max_bytes)
    if args.mode == "csv":
        return csv_map(path, args.needle or "", args.max_bytes, args.max_matches)
    raise SystemExit(f"unknown mode: {args.mode}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build bounded repo/log/json/csv maps for context-efficient inspection.")
    parser.add_argument("--mode", choices=["repo", "logs", "json", "csv"], default="repo")
    parser.add_argument("--root", default=".")
    parser.add_argument("--path")
    parser.add_argument("--needle", default="")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-matches", type=int, default=DEFAULT_MAX_MATCHES)
    args = parser.parse_args(argv)
    print(json.dumps(build_report(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
