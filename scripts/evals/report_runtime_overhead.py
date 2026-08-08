#!/usr/bin/env python3
"""Read versioned runtime event JSONL and calculate bounded summaries."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.runtime_observability import EVENTS, INTERACTIVE_EVENTS, SCHEMA_NAME, SCHEMA_VERSION  # noqa: E402


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
    return hashlib.sha256(line_text.encode("utf-8", errors="replace")).hexdigest()[:24]


def _write_quarantine(path: Path | None, line_number: int, reason: str, line_text: str) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"line": line_number, "reason": reason, "line_sha256": _line_hash(line_text)}, sort_keys=True) + "\n")
    except OSError:
        pass


def _compatible(value: object) -> bool:
    return isinstance(value, dict) and value.get("schema_version") == SCHEMA_VERSION and value.get("schema_name") == SCHEMA_NAME and value.get("event") in EVENTS


def read_jsonl(paths: Iterable[Path], *, quarantine_path: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    stats = {"files": 0, "lines": 0, "valid": 0, "corrupt": 0, "incompatible": 0}
    for path in sorted((Path(item) for item in paths), key=lambda item: str(item)):
        stats["files"] += 1
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            stats["corrupt"] += 1
            _write_quarantine(quarantine_path, 0, "file_unreadable", str(path))
            continue
        with handle:
            for line_number, line in enumerate(handle, start=1):
                stats["lines"] += 1
                if not line.strip():
                    continue
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
    return records, stats


def group_report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    durations = [number / 1_000_000 for record in records if (number := _number(record.get("monotonic_duration_ns"))) is not None]
    def total(field: str) -> int:
        return sum(int(_number(record.get(field)) or 0) for record in records)
    return {
        "count": len(records),
        "runtime_p50_ms": round(percentile(durations, 50), 3) if durations else None,
        "runtime_p95_ms": round(percentile(durations, 95), 3) if durations else None,
        "process_count": total("process_count"),
        "child_process_count": total("child_process_count"),
        "output_bytes": total("output_bytes"),
        "estimated_context_units": total("estimated_context_units"),
        "persistence_bytes": total("persistence_bytes"),
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
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
            rows = value if isinstance(value, list) else value.get("rows", []) if isinstance(value, dict) else []
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
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
    for record in records:
        key = (str(record.get("profile") or "unknown"), str(record.get("model_family") or "unknown"), str(record.get("event") or "unknown"), str(record.get("scenario") or "unspecified"))
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
            f"| {group['profile']} | {group['model_family']} | {group['event']} | {group['scenario']} | {group['count']} | {group['runtime_p50_ms']} | {group['runtime_p95_ms']} | {group['estimated_context_units']} | {group['persistence_bytes']} |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    return "\n".join(lines) + "\n"


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
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
