#!/usr/bin/env python3
"""Deterministic, offline quality/overhead eval for bounded delegation routing."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.subagent_routing import LUNA_DEFAULT_EFFORT, LUNA_MODEL, ExecutorDefaults, RoutingRequest, resolve_subagent_routing


FIXTURES: tuple[dict[str, object], ...] = (
    {
        "name": "small_bugfix",
        "complexity": 2,
        "intent": "implementation",
        "expected_route": "none",
        "expected_jobs": 0,
    },
    {
        "name": "medium_refactor",
        "complexity": 5,
        "intent": "implementation",
        "expected_route": "none",
        "expected_jobs": 0,
    },
    {
        "name": "architecture_review",
        "complexity": 8,
        "intent": "architecture",
        "expected_route": "sol-advisor",
        "expected_jobs": 1,
    },
    {
        "name": "failing_tests",
        "complexity": 9,
        "intent": "debugging",
        "failure_fingerprints": ("fixture-failure-a", "fixture-failure-b"),
        "expected_route": "sol-advisor",
        "expected_jobs": 1,
    },
)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def evaluate(iterations: int = 5) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for fixture in FIXTURES:
        samples: list[float] = []
        decisions = []
        for _ in range(max(1, iterations)):
            started = time.perf_counter_ns()
            decision = resolve_subagent_routing(
                RoutingRequest(
                    raw_complexity=int(fixture["complexity"]),
                    intent=str(fixture["intent"]),
                    repository_default=ExecutorDefaults(LUNA_MODEL, LUNA_DEFAULT_EFFORT),
                    failure_fingerprints=tuple(fixture.get("failure_fingerprints", ())),
                )
            )
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
            decisions.append(decision)
        decision = decisions[-1]
        expected_route = str(fixture["expected_route"])
        expected_jobs = int(fixture["expected_jobs"])
        route_ok = decision.subagent_route == expected_route
        jobs = 1 if decision.spawn_required else 0
        cases.append(
            {
                "schema_version": 1,
                "scenario": fixture["name"],
                "complexity": fixture["complexity"],
                "intent": fixture["intent"],
                "expected_route": expected_route,
                "route": decision.subagent_route,
                "first_pass_success": route_ok,
                "job_count": jobs,
                "expected_job_count": expected_jobs,
                "agents_started": 0,
                "advisors_started": 1 if decision.subagent_route == "sol-advisor" else 0,
                "runtime_p50_ms": round(statistics.median(samples), 4),
                "runtime_p95_ms": round(percentile(samples, 95), 4),
                "output_bytes": 0,
                "bytes_sent": 0,
                "bytes_received": 0,
                "subscription_usage_measured": False,
            }
        )
    success = sum(1 for case in cases if case["first_pass_success"])
    return {
        "schema_version": 1,
        "policy_version": "subagent-routing-v2",
        "iterations": max(1, iterations),
        "max_threads": 2,
        "max_depth": 1,
        "cases": cases,
        "first_pass_success_rate": round(success / len(cases), 3),
        "delegation_jobs": sum(int(case["job_count"]) for case in cases),
        "subscription_usage_measured": False,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Bounded subagent routing eval",
        "",
        f"- Policy: `{report['policy_version']}`",
        f"- First-pass success: `{report['first_pass_success_rate']}`",
        f"- Max threads/depth: `{report['max_threads']}` / `{report['max_depth']}`",
        "",
        "| Scenario | Route | Jobs | First pass | p50 ms | p95 ms |",
        "|---|---|---:|---|---:|---:|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['scenario']} | {case['route']} | {case['job_count']} | "
            f"{case['first_pass_success']} | {case['runtime_p50_ms']} | {case['runtime_p95_ms']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline bounded subagent routing eval.")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    report = evaluate(args.iterations)
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"METRIC routing_first_pass_success={report['first_pass_success_rate']}")
    print(f"METRIC routing_delegation_jobs={report['delegation_jobs']}")
    return 0 if report["first_pass_success_rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
