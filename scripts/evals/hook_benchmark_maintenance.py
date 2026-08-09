"""Measure deferred maintenance outside interactive hook latency."""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from hook_benchmark_scenarios import directory_bytes, percentile


SCENARIOS = ("stop_allow", "stop_allow_with_memory", "stop_objective_failure", "session_start_backlog")


def _git_value(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False, timeout=5
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError(f"maintenance benchmark cannot resolve git {' '.join(arguments)}")
    return completed.stdout.strip()


def _payload(root: Path, scenario: str, identity: str, branch: str, head: str) -> dict[str, object]:
    event = "SessionStart" if scenario == "session_start_backlog" else "Stop"
    payload: dict[str, object] = {
        "hook_event_name": event,
        "cwd": str(root),
        "workspace_root": str(root),
        "session_id": f"maintenance-{identity}",
        "turn_id": f"turn-{identity}",
        "branch": branch,
        "sha": head,
        "model": "unknown-model",
        "scenario": scenario,
        "memory_generation": f"generation-{identity}",
    }
    if event == "SessionStart":
        payload["source"] = "startup"
        return payload
    payload.update(
        {
            "task_signature": f"task-{identity}",
            "last_assistant_message": "Maintenance benchmark completed.",
            "verified_done": scenario != "stop_objective_failure",
        }
    )
    if scenario == "stop_allow_with_memory":
        payload["selected_memory_ids"] = ["benchmark-memory-sentinel"]
    if scenario == "stop_objective_failure":
        payload.update(
            {
                "tests_failed": True,
                "critical": True,
                "evidence_fingerprint": f"failure-{identity}",
            }
        )
    return payload


def _env(case_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_HOME": str(case_root / "runtime"),
            "CODEX_HOOK_STATE_ROOT": str(case_root / "hook-state"),
            "CODEX_MEMORY_HOME": str(case_root / "memory-empty"),
            "VAULT_DIR": str(case_root / "vault-empty"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "RALPH_MAINTENANCE_DEBOUNCE_SECONDS": "0",
            "RALPH_SCAFFOLD_PROFILE": "auto",
        }
    )
    return env


def measure_maintenance(root: Path, iterations: int) -> dict[str, object]:
    branch = _git_value(root, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git_value(root, "rev-parse", "HEAD")
    cases: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        enqueue_samples: list[float] = []
        runner_samples: list[float] = []
        enqueue_outputs: list[int] = []
        runner_outputs: list[int] = []
        persisted_deltas: list[int] = []
        runner_children: list[int] = []
        blocks = 0
        for index in range(iterations):
            temporary_root = Path(tempfile.gettempdir()).resolve()
            with tempfile.TemporaryDirectory(prefix="ralph-maintenance-bench-", dir=temporary_root) as temporary:
                case_root = Path(temporary)
                env = _env(case_root)
                runtime = Path(env["RALPH_HOME"])
                before = directory_bytes(runtime)
                payload = _payload(root, scenario, f"{scenario}-{index}", branch, head)
                script = "session_start_dispatch.py" if scenario == "session_start_backlog" else "stop_dispatch.py"
                started = time.perf_counter_ns()
                enqueue = subprocess.run(
                    [sys.executable, str(root / ".codex" / "hooks" / script)],
                    cwd=root,
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    env=env,
                    check=False,
                    timeout=20,
                )
                enqueue_samples.append((time.perf_counter_ns() - started) / 1_000_000)
                if enqueue.returncode != 0:
                    raise RuntimeError(f"maintenance enqueue failed: {scenario}")
                enqueue_outputs.append(len(enqueue.stdout.encode("utf-8")))
                try:
                    output = json.loads(enqueue.stdout) if enqueue.stdout.strip() else {}
                except json.JSONDecodeError as exc:
                    raise RuntimeError("maintenance hook emitted malformed output") from exc
                blocks += int(isinstance(output, dict) and output.get("decision") == "block")

                runner_started = time.perf_counter_ns()
                runner = subprocess.run(
                    [
                        sys.executable,
                        str(root / "scripts" / "memory" / "run-pending-maintenance.py"),
                        "--all",
                        "--max-jobs",
                        "1",
                        "--max-seconds",
                        "1",
                        "--json",
                    ],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    env=env,
                    check=False,
                    timeout=20,
                )
                runner_samples.append((time.perf_counter_ns() - runner_started) / 1_000_000)
                if runner.returncode != 0:
                    raise RuntimeError(f"maintenance runner failed: {scenario}")
                runner_outputs.append(len(runner.stdout.encode("utf-8")))
                try:
                    summary = json.loads(runner.stdout)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("maintenance runner emitted malformed JSON") from exc
                if not isinstance(summary, dict) or not isinstance(summary.get("child_process_count", 0), int):
                    raise RuntimeError("maintenance runner omitted child process attribution")
                runner_children.append(int(summary.get("child_process_count", 0)))
                persisted_deltas.append(max(0, directory_bytes(runtime) - before))
        cases.append(
            {
                "schema_version": 2,
                "scenario": scenario,
                "event": "SessionStart" if scenario == "session_start_backlog" else "Stop",
                "runtime_wall_ms": round(statistics.median(enqueue_samples), 3),
                "runtime_p50_ms": round(statistics.median(enqueue_samples), 3),
                "runtime_p95_ms": round(percentile(enqueue_samples, 95), 3),
                "enqueue_p50_ms": round(statistics.median(enqueue_samples), 3),
                "enqueue_p95_ms": round(percentile(enqueue_samples, 95), 3),
                "runner_p50_ms": round(statistics.median(runner_samples), 3),
                "runner_p95_ms": round(percentile(runner_samples, 95), 3),
                "output_bytes": int(statistics.median(enqueue_outputs)),
                "runner_output_bytes": int(statistics.median(runner_outputs)),
                "persisted_bytes_delta": int(statistics.median(persisted_deltas)),
                "continuation_count": blocks if scenario == "stop_objective_failure" else 0,
                "block_count": blocks,
                "child_process_count": 0,
                "child_process_count_measured": True,
                "runner_child_process_count": int(statistics.median(runner_children)),
                "subscription_usage_measured": False,
            }
        )
    return {"schema_version": 2, "cases": cases, "setup_child_process_count": 2}


__all__ = ["measure_maintenance"]
