#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _eval_common import REPO_ROOT, now_iso
from _mcp_eval_common import append_eval_jsonl, live_skip_report, load_json, load_response, mean, ratio, write_eval_report

sys.path.insert(0, str(REPO_ROOT / "scripts" / "cost"))
from _cost_common import route_task  # noqa: E402


DEFAULT_FIXTURE = REPO_ROOT / "tests" / "evals" / "fixtures" / "coding_model_tasks" / "manifest.json"


def result_by_id(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in response.get("tasks", [])}


def score_coding_router(fixture: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    live_results = result_by_id(response)
    tasks = fixture.get("tasks", [])
    route_hits = 0
    accepted = 0
    rework = 0
    latency_values: list[float] = []
    sensitive_incidents = 0
    evaluated = 0
    non_blocked = 0

    details = []
    for task in tasks:
        routed = route_task(task["task_type"], task["complexity"], task["sensitivity"])
        observed = live_results.get(task["id"], {})
        actual_route = observed.get("actual_route", routed["route"])
        actual_tool = observed.get("actual_tool", routed.get("tool"))
        expected_tool = task.get("expected_tool")
        route_ok = actual_route == task["expected_route"] and (expected_tool is None or actual_tool == expected_tool)
        route_hits += 1 if route_ok else 0
        evaluated += 1

        blocked = bool(routed["blocked"])
        externalized = bool(observed.get("externalized", task.get("externalized", False)))
        if task["sensitivity"].upper() == "RED" and externalized:
            sensitive_incidents += 1
        if not blocked:
            non_blocked += 1
            accepted += 1 if bool(observed.get("accepted", task.get("accepted", False))) else 0
            rework += 1 if bool(observed.get("rework_required", task.get("rework_required", False))) else 0
            latency_values.append(float(observed.get("latency_ms", task.get("latency_ms", fixture.get("latency_budget_ms", 1)))))

        details.append(
            {
                "id": task["id"],
                "expected_route": task["expected_route"],
                "actual_route": actual_route,
                "expected_tool": expected_tool,
                "actual_tool": actual_tool,
                "route_ok": route_ok,
                "blocked": blocked,
                "externalized": externalized,
            }
        )

    budget = float(fixture.get("latency_budget_ms", 1))
    avg_latency = round(sum(latency_values) / len(latency_values), 2) if latency_values else 0.0
    latency_score = 1.0 if avg_latency <= budget else max(0.0, round(budget / avg_latency, 4))
    rework_rate = 1.0 - ratio(non_blocked - rework, non_blocked)
    incident_score = 1.0 if sensitive_incidents == 0 else 0.0
    metrics = {
        "route_correctness": ratio(route_hits, evaluated),
        "acceptance_rate": ratio(accepted, non_blocked),
        "rework_rate": round(rework_rate, 4),
        "latency": latency_score,
        "sensitive_externalization_incidents": sensitive_incidents,
    }
    score = mean([
        metrics["route_correctness"],
        metrics["acceptance_rate"],
        1.0 - metrics["rework_rate"],
        metrics["latency"],
        incident_score,
    ])
    return {
        "metrics": metrics,
        "latency_ms_avg": avg_latency,
        "score": score,
        "details": details,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    fixture = load_json(Path(args.fixture))
    response, status = load_response(fixture, args.mode, args.live_response)
    suite = fixture["suite"]
    target_mcps = fixture.get("target_mcps", [])
    if response is None:
        return live_skip_report(suite, args.mode, target_mcps, args.output)

    scored = score_coding_router(fixture, response)
    report = {
        "created_at": now_iso(),
        "suite": suite,
        "mode": args.mode,
        "status": status,
        "target_mcps": target_mcps,
        **scored,
    }
    write_eval_report(suite, report, args.output)
    append_eval_jsonl(suite, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate ralph_coding_models routing outcomes in mock or live mode.")
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--live-response", default=None, help="Sanitized MCP response JSON for live mode.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = build_report(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
