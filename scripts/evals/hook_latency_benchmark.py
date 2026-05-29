#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_ROOT = REPO_ROOT / ".codex" / "hooks"
if str(HOOKS_ROOT) not in sys.path:
    sys.path.insert(0, str(HOOKS_ROOT))

from shared.active_context import active_context_from_payload  # noqa: E402
from shared.autoresearch_observer import observe_post_tool_payload  # noqa: E402


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]


def write_active_session(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "autoresearch.md").write_text("# AutoResearch\n", encoding="utf-8")
    (workspace / "autoresearch.jsonl").write_text(
        json.dumps({"entry_type": "config", "segment_id": "latency", "metric": "seconds", "direction": "lower"})
        + "\n",
        encoding="utf-8",
    )


def measure(iterations: int, active: bool) -> dict[str, float]:
    with tempfile.TemporaryDirectory(prefix="ralph-hook-latency-") as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        workspace.mkdir()
        if active:
            write_active_session(workspace)
        os.environ["RALPH_HOME"] = str(root / "ralph")
        payload = {
            "cwd": str(workspace),
            "session_id": "latency-session",
            "success": True,
            "tool_input": {"command": "python benchmark.py"},
            "output": "METRIC seconds=1\n",
        }
        context = active_context_from_payload(payload)
        samples: list[float] = []
        for _ in range(iterations):
            start = time.perf_counter()
            observe_post_tool_payload(payload, context)
            samples.append((time.perf_counter() - start) * 1000)
    return {
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(percentile(samples, 95), 3),
        "max_ms": round(max(samples), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure lightweight AutoResearch hook observer overhead.")
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    report = {
        "iterations": args.iterations,
        "no_active_session": measure(args.iterations, active=False),
        "active_session": measure(args.iterations, active=True),
    }
    report["metric"] = report["active_session"]["p95_ms"]
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"METRIC hook_overhead_p95_ms={report['metric']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
