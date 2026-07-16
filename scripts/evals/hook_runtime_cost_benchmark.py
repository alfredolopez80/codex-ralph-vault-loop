#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
USER_PROMPT_HOOKS = (
    ("universal_prompt_classifier", ["bash", str(HOOKS / "universal-prompt-classifier.sh")]),
    ("user_prompt_capture", [sys.executable, str(HOOKS / "user_prompt_capture.py")]),
    ("user_prompt_improve", [sys.executable, str(HOOKS / "user_prompt_improve.py")]),
    ("continuity_prompt_context", [sys.executable, str(HOOKS / "continuity_prompt_context.py")]),
)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]


def estimate_context_units(chars: int) -> int:
    return max(0, (chars + 3) // 4)


def payloads() -> list[dict[str, str]]:
    return [
        {
            "name": "simple",
            "prompt": "ok revisa hooks y memoria del repo para rendimiento",
        },
        {
            "name": "implementation",
            "prompt": "Optimize Codex hooks for faster execution and compact context output while keeping recall and safety features",
        },
        {
            "name": "continuation",
            "prompt": "continua donde quedamos",
        },
    ]


def session_id_for(payload: dict[str, str], iteration: int) -> str:
    return f"hook-cost-{payload['name']}-{iteration}"


def hook_payload(payload: dict[str, str], iteration: int, prompt: str | None = None) -> str:
    return json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id_for(payload, iteration),
            "cwd": str(ROOT),
            "prompt": prompt if prompt is not None else payload["prompt"],
        }
    )


def seed_continuation_checkpoint(payload: dict[str, str], iteration: int, env: dict[str, str]) -> None:
    completed = subprocess.run(
        [sys.executable, str(HOOKS / "continuity_prompt_context.py")],
        cwd=ROOT,
        input=hook_payload(
            payload,
            iteration,
            "Optimize Codex hooks for faster execution while preserving memory checkpoints",
        ),
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"continuity seed failed: {completed.stderr[-500:]}")


def run_once(command: list[str], payload: dict[str, str], env: dict[str, str], iteration: int) -> tuple[float, int]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        input=hook_payload(payload, iteration),
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    if completed.returncode != 0:
        raise RuntimeError(f"{Path(command[-1]).name} failed: {completed.stderr[-500:]}")
    return elapsed_ms, len(completed.stdout.strip())


def measure(iterations: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="ralph-hook-cost-") as tmp:
        env = os.environ.copy()
        env["RALPH_HOME"] = str(Path(tmp) / "ralph")
        env["CODEX_MEMORY_HOME"] = str(Path(tmp) / "codex-memory-empty")
        env["VAULT_DIR"] = str(Path(tmp) / "vault-empty")
        env["RALPH_LOCAL_NOTES_ROOTS"] = ""
        env.pop("RALPH_MEMORY_TRACE", None)

        cases: list[dict[str, object]] = []
        total_p50_ms = 0.0
        total_stdout_chars = 0
        for payload in payloads():
            for hook_name, command in USER_PROMPT_HOOKS:
                samples: list[float] = []
                stdout_sizes: list[int] = []
                for iteration in range(iterations):
                    if payload["name"] == "continuation" and hook_name == "continuity_prompt_context":
                        seed_continuation_checkpoint(payload, iteration, env)
                    elapsed_ms, stdout_chars = run_once(command, payload, env, iteration)
                    samples.append(elapsed_ms)
                    stdout_sizes.append(stdout_chars)
                p50_ms = statistics.median(samples)
                p95_ms = percentile(samples, 95)
                stdout_chars = int(statistics.median(stdout_sizes))
                total_p50_ms += p50_ms
                total_stdout_chars += stdout_chars
                cases.append(
                    {
                        "payload": payload["name"],
                        "hook": hook_name,
                        "p50_ms": round(p50_ms, 3),
                        "p95_ms": round(p95_ms, 3),
                        "stdout_chars": stdout_chars,
                        "context_units": estimate_context_units(stdout_chars),
                    }
                )

    output_units = estimate_context_units(total_stdout_chars)
    score = total_p50_ms + (output_units * 2.0)
    return {
        "iterations": iterations,
        "cases": cases,
        "total_p50_ms": round(total_p50_ms, 3),
        "total_stdout_chars": total_stdout_chars,
        "estimated_context_units": output_units,
        "hook_cost_score": round(score, 3),
    }


def main() -> int:
    iterations = int(os.environ.get("RALPH_HOOK_COST_ITERATIONS", "3"))
    report = measure(max(1, iterations))
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"METRIC hook_cost_score={report['hook_cost_score']}")
    print(f"METRIC hook_total_p50_ms={report['total_p50_ms']}")
    print(f"METRIC hook_output_context_units={report['estimated_context_units']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
