#!/usr/bin/env python3
"""Read versioned runtime event JSONL and calculate bounded summaries."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.paths import _is_allowed_system_alias  # noqa: E402
from shared.runtime_observability import EVENTS, INTERACTIVE_EVENTS, SCHEMA_NAME, SCHEMA_VERSION  # noqa: E402


MAX_INPUT_FILE_BYTES = 32 * 1024 * 1024
MAX_INPUT_FILES = 64
MAX_INPUT_RECORDS = 100_000
MAX_USAGE_BYTES = 2 * 1024 * 1024
MAX_USAGE_ROWS = 100_000
MAX_GROUPS = 4_096
MAX_QUARANTINE_BYTES = 1 * 1024 * 1024
MAX_QUARANTINE_LINE_BYTES = 4 * 1024
MAX_REPORT_OUTPUT_BYTES = 512 * 1024


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, round((max(0.0, min(100.0, pct)) / 100.0) * (len(ordered) - 1)))
    return ordered[index]


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _line_hash(line_text: str) -> str:
    bounded = line_text[:MAX_QUARANTINE_LINE_BYTES]
    return hashlib.sha256(bounded.encode("utf-8", errors="replace")).hexdigest()[:24]


def _write_quarantine(path: Path | None, line_number: int, reason: str, line_text: str) -> None:
    if path is None:
        return
    try:
        _safe_parent(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps({"line": line_number, "reason": reason, "line_sha256": _line_hash(line_text)}, sort_keys=True) + "\n").encode("utf-8")
        if path.exists() and path.stat().st_size + len(encoded) > MAX_QUARANTINE_BYTES:
            return
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size + len(encoded) > MAX_QUARANTINE_BYTES:
                return
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    return
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _safe_parent(path: Path) -> None:
    absolute = path.expanduser().absolute()
    current = Path(absolute.parts[0])
    for part in absolute.parts[1:-1]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) and not _is_allowed_system_alias(current):
            raise OSError("report output parent contains a symlink")
        if not _is_allowed_system_alias(current) and not stat.S_ISDIR(info.st_mode):
            raise OSError("report output parent is not a directory")


def _compatible(value: object) -> bool:
    return isinstance(value, dict) and value.get("schema_version") == SCHEMA_VERSION and value.get("schema_name") == SCHEMA_NAME and value.get("event") in EVENTS


def _bounded_lines(path: Path, *, max_bytes: int = MAX_INPUT_FILE_BYTES):
    """Yield one bounded file's lines from a stable, no-follow descriptor."""
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise OSError("input is not a regular non-aliased file")
    if before.st_size > max_bytes:
        raise OverflowError("input file exceeds its byte limit")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size > max_bytes
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise OSError("input changed during open")
        total = 0
        with os.fdopen(fd, "rb") as handle:
            for raw_line in handle:
                total += len(raw_line)
                if total > max_bytes:
                    raise OverflowError("input file exceeds its byte limit")
                yield raw_line.decode("utf-8", errors="replace")
            final = os.fstat(handle.fileno())
            if (
                final.st_dev != opened.st_dev
                or final.st_ino != opened.st_ino
                or final.st_nlink != 1
                or final.st_size != total
            ):
                raise OSError("input changed during read")
    finally:
        # os.fdopen closes the descriptor after normal iteration.  Closing an
        # already closed descriptor is harmlessly avoided by the context.
        pass


def read_jsonl(paths: Iterable[Path], *, quarantine_path: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    stats = {"files": 0, "lines": 0, "valid": 0, "corrupt": 0, "incompatible": 0, "truncated": 0}
    for file_index, path in enumerate(sorted((Path(item) for item in paths), key=lambda item: str(item))):
        if file_index >= MAX_INPUT_FILES:
            stats["corrupt"] += 1
            stats["truncated"] += 1
            _write_quarantine(quarantine_path, 0, "file_limit", str(path))
            break
        stats["files"] += 1
        try:
            lines = _bounded_lines(path)
            try:
                for line_number, line in enumerate(lines, start=1):
                    stats["lines"] += 1
                    if not line.strip():
                        continue
                    if len(records) >= MAX_INPUT_RECORDS:
                        stats["corrupt"] += 1
                        stats["truncated"] += 1
                        _write_quarantine(quarantine_path, line_number, "record_limit", line)
                        break
                    try:
                        value = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        stats["corrupt"] += 1
                        _write_quarantine(quarantine_path, line_number, "invalid_json", line)
                        continue
                    if not _compatible(value):
                        stats["incompatible"] += 1
                        _write_quarantine(quarantine_path, line_number, "incompatible_schema", line)
                        continue
                    records.append(value)
                    stats["valid"] += 1
            finally:
                lines.close()
            continue
        except OverflowError:
            stats["corrupt"] += 1
            stats["truncated"] += 1
            _write_quarantine(quarantine_path, 0, "file_limit", str(path))
            continue
        except OSError:
            stats["corrupt"] += 1
            _write_quarantine(quarantine_path, 0, "file_unreadable", str(path))
    return records, stats


def group_report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    durations = [number / 1_000_000 for record in records if (number := _number(record.get("monotonic_duration_ns"))) is not None]
    def total(field: str) -> int:
        return sum(int(_number(record.get(field)) or 0) for record in records)
    persistence_values = [_number(record.get("persistence_bytes")) for record in records]
    persistence_unknown = sum(value is None for value in persistence_values)
    return {
        "count": len(records),
        "runtime_p50_ms": round(percentile(durations, 50), 3) if durations else None,
        "runtime_p95_ms": round(percentile(durations, 95), 3) if durations else None,
        "process_count": total("process_count"),
        "child_process_count": total("child_process_count"),
        "output_bytes": total("output_bytes"),
        "estimated_context_units": total("estimated_context_units"),
        # A partial total is misleading when one writer did not expose a
        # bounded result.  Keep the metric explicitly unknown instead of
        # converting unavailable cost to zero.
        "persistence_bytes": None if persistence_unknown else int(sum(value or 0 for value in persistence_values)),
        "persistence_bytes_known": persistence_unknown == 0,
        "persistence_unknown_count": persistence_unknown,
        "continuation_count": total("continuation_count"),
        "advisor_count": total("advisor_count"),
    }


def _usage_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        from datetime import datetime

        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return True


def load_user_usage(path: Path | None) -> dict[str, Any] | None:
    """Load an optional user-provided export without network or account access."""
    if path is None:
        return None
    rows: list[Mapping[str, Any]] = []
    try:
        raw = b"".join(line.encode("utf-8", errors="replace") for line in _bounded_lines(path, max_bytes=MAX_USAGE_BYTES))
        text = raw.decode("utf-8")
        if path.suffix.lower() == ".csv":
            rows = list(csv.DictReader(io.StringIO(text)))
        else:
            value = json.loads(text)
            rows = value if isinstance(value, list) else value.get("rows", []) if isinstance(value, dict) else []
        if len(rows) > MAX_USAGE_ROWS:
            rows = rows[:MAX_USAGE_ROWS]
    except (OSError, OverflowError, json.JSONDecodeError, TypeError, ValueError, UnicodeError):
        return {"source": "user_supplied_usage", "verified": False, "rows_accepted": 0, "rows_rejected": 1, "ambiguous_rows": 0}
    accepted: list[float] = []
    rejected = 0
    ambiguous = 0
    for row in rows:
        if not isinstance(row, Mapping) or not _usage_timestamp(row.get("timestamp")):
            ambiguous += 1
            continue
        value = _number(row.get("usage_units") or row.get("units"))
        if value is None:
            rejected += 1
            continue
        accepted.append(value)
    return {
        "source": "user_supplied_usage",
        "verified": False,
        "rows_accepted": len(accepted),
        "rows_rejected": rejected,
        "ambiguous_rows": ambiguous,
        "usage_units_total": round(sum(accepted), 6),
        "subscription_usage_measured": False,
    }


def build_report(
    records: Sequence[Mapping[str, Any]],
    stats: Mapping[str, int] | None = None,
    *,
    usage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_stats = dict(stats or {"files": 0, "lines": len(records), "valid": len(records), "corrupt": 0, "incompatible": 0})
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    unique_keys: set[tuple[str, str, str, str]] = set()
    for record in records:
        key = (str(record.get("profile") or "unknown"), str(record.get("model_family") or "unknown"), str(record.get("event") or "unknown"), str(record.get("scenario") or "unspecified"))
        unique_keys.add(key)
        if key in groups or len(groups) < MAX_GROUPS:
            groups.setdefault(key, []).append(record)
    grouped = [{"profile": key[0], "model_family": key[1], "event": key[2], "scenario": key[3], **group_report(groups[key])} for key in sorted(groups)]
    interactive = [record for record in records if record.get("event") in INTERACTIVE_EVENTS]
    maintenance = [record for record in records if record.get("event") == "maintenance"]
    confidence = "low" if not records else "medium" if source_stats.get("corrupt", 0) or source_stats.get("incompatible", 0) or len(records) < 5 else "high"
    return {
        "schema_version": SCHEMA_VERSION,
        "schema_name": SCHEMA_NAME,
        "subscription_usage_measured": False,
        "input": source_stats,
        "confidence": {"level": confidence, "reason": "compatible events" if confidence == "high" else "bounded sample or quarantined lines"},
        "interactive": group_report(interactive),
        "maintenance_deferred": group_report(maintenance),
        "groups": grouped,
        "groups_omitted": max(0, len(unique_keys) - len(grouped)),
        "usage": dict(usage) if usage is not None else None,
        "limitations": [
            "estimated_context_units is ceil(output_bytes / 4), a local approximation rather than model accounting",
            "internal units, cached input, output billing, account limits, and credits are not observable here",
            "maintenance is reported separately and excluded from interactive totals",
            "optional usage data is user supplied, unverified, and never joined by ambiguous timestamps",
        ],
    }


def markdown_report(report: Mapping[str, Any]) -> str:
    interactive = report.get("interactive", {})
    maintenance = report.get("maintenance_deferred", {})
    lines = [
        "# Ralph runtime overhead report",
        "",
        f"- Schema: `{report.get('schema_name')}` v{report.get('schema_version')}",
        f"- Confidence: **{report.get('confidence', {}).get('level', 'low')}** ({report.get('confidence', {}).get('reason', 'unknown')})",
        "- `subscription_usage_measured`: **false**",
        "",
        "## Interactive hooks",
        "",
        "| observations | p50 ms | p95 ms | child processes | output bytes | context units | continuations | advisors |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {interactive.get('count', 0)} | {interactive.get('runtime_p50_ms')} | {interactive.get('runtime_p95_ms')} | {interactive.get('child_process_count', 0)} | {interactive.get('output_bytes', 0)} | {interactive.get('estimated_context_units', 0)} | {interactive.get('continuation_count', 0)} | {interactive.get('advisor_count', 0)} |",
        "",
        "## Deferred maintenance (excluded from interactive timing)",
        "",
        f"- observations: {maintenance.get('count', 0)}; p50/p95: {maintenance.get('runtime_p50_ms')}/{maintenance.get('runtime_p95_ms')} ms; child processes: {maintenance.get('child_process_count', 0)}",
        "",
        "## Groups",
        "",
        "| profile | model family | event | scenario | n | p50 ms | p95 ms | context units | persistence bytes |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in report.get("groups", []):
        lines.append(
            f"| {group['profile']} | {group['model_family']} | {group['event']} | {group['scenario']} | {group['count']} | {group['runtime_p50_ms']} | {group['runtime_p95_ms']} | {group['estimated_context_units']} | {group['persistence_bytes'] if group.get('persistence_bytes_known', False) else 'unknown'} |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    return "\n".join(lines) + "\n"


def _write_output(path: Path, encoded: bytes) -> None:
    """Publish one bounded report without following a target alias."""
    path = path.expanduser()
    _safe_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        previous = path.lstat()
        if stat.S_ISLNK(previous.st_mode) or not stat.S_ISREG(previous.st_mode) or previous.st_nlink != 1:
            raise OSError("report output target is not a private regular file")
        mode = stat.S_IMODE(previous.st_mode)
    except FileNotFoundError:
        previous = None
        mode = 0o600
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            os.fchmod(handle.fileno(), mode & 0o777 or 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            current = path.lstat()
        except FileNotFoundError:
            current = None
        if previous is None:
            if current is not None:
                raise OSError("report output target appeared during publication")
        elif current is None or (current.st_dev, current.st_ino) != (previous.st_dev, previous.st_ino):
            raise OSError("report output target changed during publication")
        os.replace(temporary, path)
        temporary = ""
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary:
            with suppress(OSError):
                Path(temporary).unlink()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report Ralph runtime overhead.")
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--quarantine-out", type=Path)
    parser.add_argument("--usage", type=Path, help="Optional user-provided CSV/JSON export.")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)
    records, stats = read_jsonl(args.input, quarantine_path=args.quarantine_out)
    report = build_report(records, stats, usage=load_user_usage(args.usage))
    encoded = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    markdown = markdown_report(report)
    if len(encoded.encode("utf-8")) > MAX_REPORT_OUTPUT_BYTES or len(markdown.encode("utf-8")) > MAX_REPORT_OUTPUT_BYTES:
        sys.stderr.write("runtime overhead report exceeds its bounded output limit\n")
        return 8
    if args.json_out:
        _write_output(args.json_out, encoded.encode("utf-8"))
    else:
        sys.stdout.write(encoded)
    if args.markdown_out:
        _write_output(args.markdown_out, markdown.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
