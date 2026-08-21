#!/usr/bin/env python3
"""Run reproducible, privacy-safe hook runtime scenarios."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from hook_benchmark_config import configured_handler_counts, load_hook_config, matched_handlers
from hook_benchmark_maintenance import measure_maintenance
from hook_benchmark_results import measure_scenarios
from hook_benchmark_scenarios import PROFILES, SCENARIOS, percentile
from hook_benchmark_scope import measure_scopes


ROOT = Path(__file__).resolve().parents[2]
HOOK_CONFIG = ROOT / ".codex" / "hooks.json"
SCHEMA_VERSION = 2


def estimate_context_units(output_bytes: int) -> int:
    return max(0, (output_bytes + 3) // 4)


def measure(iterations: int, *, warmup: int = 0, include_maintenance: bool = True) -> dict[str, object]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if warmup < 0:
        raise ValueError("warmup must not be negative")
    config = load_hook_config(HOOK_CONFIG)
    counts = configured_handler_counts(config)
    matrix = measure_scenarios(config, ROOT, iterations, warmup)
    scope_cases = measure_scopes(config, ROOT, iterations)
    maintenance = measure_maintenance(ROOT, iterations) if include_maintenance else {
        "schema_version": SCHEMA_VERSION,
        "cases": [],
        "skipped_reason": "explicit_skip",
    }
    total_p50_ms = round(sum(float(case["runtime_p50_ms"]) for case in matrix), 3)
    total_p95_ms = round(sum(float(case["runtime_p95_ms"]) for case in matrix), 3)
    total_output = sum(int(case["output_bytes"]) for case in matrix)
    context_units = estimate_context_units(total_output)
    measured_children = all(case.get("child_process_count_measured") is True for case in matrix)
    child_total = sum(int(case["child_process_count"]) for case in matrix) if measured_children else None
    return {
        "schema_version": SCHEMA_VERSION,
        "iterations": iterations,
        "warmup_iterations": warmup,
        "scenario_names": list(SCENARIOS),
        "profiles": list(PROFILES),
        "scenario_matrix": matrix,
        "scope_cases": scope_cases,
        "cases": matrix,
        "configured_handlers_by_event": counts,
        "matched_handler_count": sum(int(case["matched_handler_count"]) for case in matrix),
        "executed_handler_count": sum(int(case["executed_handler_count"]) for case in matrix),
        "process_count": sum(int(case["process_count"]) for case in matrix),
        "child_process_count": child_total,
        "child_process_count_measured": measured_children,
        "block_count": sum(int(case["block_count"]) for case in matrix),
        "continuation_count": sum(int(case["continuation_count"]) for case in matrix),
        "advisor_count": sum(int(case["advisor_count"]) for case in matrix),
        "cache_hits": sum(int(case["cache_hits"]) for case in matrix),
        "persisted_bytes_delta": sum(int(case["persisted_bytes_delta"]) for case in matrix),
        "total_p50_ms": total_p50_ms,
        "total_p95_ms": total_p95_ms,
        "total_stdout_chars": total_output,
        "estimated_context_units": context_units,
        "hook_cost_score": round(total_p50_ms + (context_units * 2.0), 3),
        "effective_stdout_chars_by_event": {
            event: sum(int(case["output_bytes"]) for case in matrix if event in str(case["event"]).split("+"))
            for event in counts
        },
        "duplicate_roles": [],
        "suppressed_roles": sorted({str(case["role"]) for case in scope_cases if case["source_scope"] == "suppressed-global"}),
        "source_scopes_measured": ["project", "global", "suppressed-global"],
        "source_scopes_not_measured": [],
        "successful_post_tool_stdout_chars": sum(
            int(case["output_bytes"])
            for case in matrix
            if "PostToolUse" in str(case["event"]).split("+") and int(case["block_count"]) == 0
        ),
        "successful_stop_stdout_chars": sum(
            int(case["output_bytes"])
            for case in matrix
            if str(case["event"]) == "Stop" and int(case["block_count"]) == 0
        ),
        "subscription_usage_measured": False,
        "post_tool_processes_before": None,
        "post_tool_processes_after": counts.get("PostToolUse"),
        "post_tool_processes_reduction": None,
        "active_post_tool_roles": sorted({str(case["role"]) for case in scope_cases if case["event"] == "PostToolUse"}),
        "stop_processes_before": None,
        "stop_processes_after": counts.get("Stop"),
        "stop_processes_reduction": None,
        "active_stop_roles": sorted({str(case["role"]) for case in scope_cases if case["event"] == "Stop"}),
        "session_start": {
            "schema_version": SCHEMA_VERSION,
            "cases": [case for case in matrix if str(case["scenario"]).startswith("session_start_")],
        },
        "maintenance": maintenance,
        "limitations": [
            "No provider or account usage is measured.",
            "Context units are estimated as ceil(output bytes / 4).",
            "Deferred maintenance time is excluded from interactive scenario runtime.",
            "Global scope timing measures the wrapper and its configured child; project scenarios time the configured child directly.",
        ],
    }


def markdown_report(report: Mapping[str, object]) -> str:
    lines = [
        "# Hook runtime benchmark",
        "",
        f"- Schema: `{report.get('schema_version')}`",
        f"- Measured iterations: `{report.get('iterations')}` after `{report.get('warmup_iterations')}` warmup iteration(s)",
        f"- Aggregate p50/p95: `{report.get('total_p50_ms')} ms` / `{report.get('total_p95_ms')} ms`",
        f"- Subscription usage measured: `{report.get('subscription_usage_measured')}`",
        "",
        "| Scenario | Profile | Event | configured | matched | executed | children | p50 ms | p95 ms | output B | persisted B | blocks | continuations | cache hits |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    matrix = report.get("scenario_matrix", [])
    for case in matrix if isinstance(matrix, list) else []:
        if not isinstance(case, Mapping):
            continue
        child = case.get("child_process_count") if case.get("child_process_count_measured") else "unknown"
        lines.append(
            "| {scenario} | {profile} | {event} | {configured} | {matched} | {executed} | {child} | {p50} | {p95} | {output} | {persisted} | {blocks} | {continuations} | {hits} |".format(
                scenario=case.get("scenario"),
                profile=case.get("profile"),
                event=case.get("event"),
                configured=case.get("configured_handler_count"),
                matched=case.get("matched_handler_count"),
                executed=case.get("executed_handler_count"),
                child=child,
                p50=case.get("runtime_p50_ms"),
                p95=case.get("runtime_p95_ms"),
                output=case.get("output_bytes"),
                persisted=case.get("persisted_bytes_delta"),
                blocks=case.get("block_count"),
                continuations=case.get("continuation_count"),
                hits=case.get("cache_hits"),
            )
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in report.get("limitations", []) if isinstance(item, str)],
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--warmup", type=int)
    parser.add_argument("--skip-maintenance", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)
    iterations = args.iterations if args.iterations is not None else int(os.environ.get("RALPH_HOOK_COST_ITERATIONS", "3"))
    warmup = args.warmup if args.warmup is not None else int(os.environ.get("RALPH_HOOK_COST_WARMUP", "1"))
    report = measure(iterations, warmup=warmup, include_maintenance=not args.skip_maintenance)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown_report(report), encoding="utf-8")
    if args.json_out or args.markdown_out:
        destinations = []
        if args.json_out:
            destinations.append(f"json={args.json_out}")
        if args.markdown_out:
            destinations.append(f"markdown={args.markdown_out}")
        print("HOOK_BENCHMARK_REPORT " + " ".join(destinations))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    print(f"METRIC hook_cost_score={report['hook_cost_score']}")
    print(f"METRIC hook_total_p50_ms={report['total_p50_ms']}")
    print(f"METRIC hook_output_context_units={report['estimated_context_units']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SCHEMA_VERSION",
    "configured_handler_counts",
    "estimate_context_units",
    "load_hook_config",
    "main",
    "markdown_report",
    "matched_handlers",
    "measure",
    "percentile",
]
