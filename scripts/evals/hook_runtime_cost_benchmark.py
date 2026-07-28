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
sys.path.insert(0, str(HOOKS))
from global_hook_dispatch import ROLE_COMMANDS

USER_PROMPT_HOOKS = (
    ("universal_prompt_classifier", ["bash", str(HOOKS / "universal-prompt-classifier.sh")]),
    ("user_prompt_capture", [sys.executable, str(HOOKS / "user_prompt_capture.py")]),
    ("user_prompt_improve", [sys.executable, str(HOOKS / "user_prompt_improve.py")]),
    ("continuity_prompt_context", [sys.executable, str(HOOKS / "continuity_prompt_context.py")]),
)
DISPATCHER = HOOKS / "global_hook_dispatch.py"
LIFECYCLE_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


def direct_command(event: str, role: str) -> list[str]:
    child = ROLE_COMMANDS[(event, role)]
    script = HOOKS / child[0]
    return ["bash", str(script), *child[1:]] if script.suffix == ".sh" else [sys.executable, str(script), *child[1:]]


def dispatcher_command(event: str, role: str) -> list[str]:
    return [sys.executable, str(DISPATCHER), "--event", event, "--role", role]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1)))
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


def lifecycle_payload(event: str, workspace: Path, session_id: str) -> dict[str, object]:
    payload: dict[str, object] = {"hook_event_name": event, "cwd": str(workspace), "session_id": session_id}
    if event == "SessionStart":
        payload["source"] = "startup"
    elif event == "UserPromptSubmit":
        payload["prompt"] = "Review the effective hook pipeline without changing unrelated files."
    elif event == "PreToolUse":
        payload["tool_name"] = "exec_command"
        payload["tool_input"] = {"cmd": "git status --short", "workdir": str(workspace)}
    elif event == "PostToolUse":
        payload["tool_name"] = "exec_command"
        payload["tool_use_id"] = f"toolu_{session_id}"
        payload["tool_input"] = {"cmd": "git status --short", "workdir": str(workspace)}
        payload["tool_response"] = {"exit_code": 0, "stdout": "## branch\n"}
        payload["success"] = True
    elif event == "Stop":
        payload["last_assistant_message"] = "Completed benchmark validation."
    return payload


def run_lifecycle_once(command: list[str], payload: dict[str, object], env: dict[str, str], cwd: Path) -> tuple[float, str]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    if completed.returncode != 0:
        raise RuntimeError(f"{Path(command[-1]).name} failed: {completed.stderr[-500:]}")
    return elapsed_ms, completed.stdout


def directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def output_block_count(output: str) -> int:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return 0
    return 1 if isinstance(payload, dict) and payload.get("decision") == "block" else 0


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
                        "event": "UserPromptSubmit",
                        "role": hook_name,
                        "effective_config": "project_only",
                        "source_scope": "project",
                        "p50_ms": round(p50_ms, 3),
                        "p95_ms": round(p95_ms, 3),
                        "runtime_p50_ms": round(p50_ms, 3),
                        "runtime_p95_ms": round(p95_ms, 3),
                        "stdout_chars": stdout_chars,
                        "context_units": estimate_context_units(stdout_chars),
                        "estimated_context_units": estimate_context_units(stdout_chars),
                        "block_count": 0,
                        "continuation_count": 1 if payload["name"] == "continuation" else 0,
                        "persisted_bytes": 0,
                    }
                )

        global_workspace = Path(tmp) / "global-only-workspace"
        global_workspace.mkdir()
        for event, role in ROLE_COMMANDS:
            for effective_config in ("project_only", "global_only", "global_plus_project"):
                samples: list[float] = []
                stdout_sizes: list[int] = []
                blocks = 0
                suppressed_samples: list[float] = []
                for iteration in range(iterations):
                    session_id = f"hook-cost-{event}-{role}-{effective_config}-{iteration}"
                    if effective_config == "project_only":
                        payload = lifecycle_payload(event, ROOT, session_id)
                        elapsed_ms, output = run_lifecycle_once(direct_command(event, role), payload, env, ROOT)
                    elif effective_config == "global_only":
                        payload = lifecycle_payload(event, global_workspace, session_id)
                        elapsed_ms, output = run_lifecycle_once(dispatcher_command(event, role), payload, env, global_workspace)
                    else:
                        payload = lifecycle_payload(event, ROOT, session_id)
                        suppressed_ms, suppressed_output = run_lifecycle_once(dispatcher_command(event, role), payload, env, ROOT)
                        if suppressed_output:
                            raise RuntimeError(f"global dispatcher did not suppress {event}/{role}")
                        suppressed_samples.append(suppressed_ms)
                        elapsed_ms, output = run_lifecycle_once(direct_command(event, role), payload, env, ROOT)
                    samples.append(elapsed_ms)
                    stdout_sizes.append(len(output.encode("utf-8")))
                    blocks += output_block_count(output)

                p50_ms = statistics.median(samples)
                p95_ms = percentile(samples, 95)
                stdout_chars = int(statistics.median(stdout_sizes))
                source_scope = "global" if effective_config == "global_only" else "project"
                cases.append(
                    {
                        "payload": "lifecycle",
                        "hook": role,
                        "event": event,
                        "role": role,
                        "effective_config": effective_config,
                        "source_scope": source_scope,
                        "p50_ms": round(p50_ms, 3),
                        "p95_ms": round(p95_ms, 3),
                        "runtime_p50_ms": round(p50_ms, 3),
                        "runtime_p95_ms": round(p95_ms, 3),
                        "stdout_chars": stdout_chars,
                        "context_units": estimate_context_units(stdout_chars),
                        "estimated_context_units": estimate_context_units(stdout_chars),
                        "block_count": blocks,
                        "continuation_count": 0,
                        "persisted_bytes": directory_bytes(Path(env["RALPH_HOME"])),
                    }
                )
                if suppressed_samples:
                    cases.append(
                        {
                            "payload": "lifecycle",
                            "hook": role,
                            "event": event,
                            "role": role,
                            "effective_config": effective_config,
                            "source_scope": "suppressed_global",
                            "p50_ms": round(statistics.median(suppressed_samples), 3),
                            "p95_ms": round(percentile(suppressed_samples, 95), 3),
                            "runtime_p50_ms": round(statistics.median(suppressed_samples), 3),
                            "runtime_p95_ms": round(percentile(suppressed_samples, 95), 3),
                            "stdout_chars": 0,
                            "context_units": 0,
                            "estimated_context_units": 0,
                            "block_count": 0,
                            "continuation_count": 0,
                            "persisted_bytes": directory_bytes(Path(env["RALPH_HOME"])),
                        }
                    )

    output_units = estimate_context_units(total_stdout_chars)
    score = total_p50_ms + (output_units * 2.0)
    effective_cases = [case for case in cases if case["source_scope"] != "suppressed_global"]
    stdout_by_event = {
        event: sum(int(case["stdout_chars"]) for case in effective_cases if case["event"] == event)
        for event in LIFECYCLE_EVENTS
    }
    units_by_event = {event: estimate_context_units(chars) for event, chars in stdout_by_event.items()}
    suppressed_roles = sorted({str(case["role"]) for case in cases if case["source_scope"] == "suppressed_global"})
    return {
        "iterations": iterations,
        "cases": cases,
        "total_p50_ms": round(total_p50_ms, 3),
        "total_stdout_chars": total_stdout_chars,
        "estimated_context_units": output_units,
        "hook_cost_score": round(score, 3),
        "effective_stdout_chars_by_event": stdout_by_event,
        "effective_context_units_by_event": units_by_event,
        "duplicate_roles": [],
        "suppressed_roles": suppressed_roles,
        "successful_post_tool_stdout_chars": sum(
            int(case["stdout_chars"])
            for case in effective_cases
            if case["event"] == "PostToolUse" and int(case["block_count"]) == 0
        ),
        "successful_stop_stdout_chars": sum(
            int(case["stdout_chars"])
            for case in effective_cases
            if case["event"] == "Stop" and int(case["block_count"]) == 0
        ),
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
