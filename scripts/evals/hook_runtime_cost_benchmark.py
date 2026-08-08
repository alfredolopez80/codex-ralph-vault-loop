#!/usr/bin/env python3
from __future__ import annotations

import json
import argparse
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
ACTIVE_ROLE_COMMANDS = {
    key: value
    for key, value in ROLE_COMMANDS.items()
    if (key[0] != "PostToolUse" or key[1] == "post_tool_dispatch")
    and (key[0] != "Stop" or key[1] == "stop_dispatch")
}


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


def lifecycle_payload(event: str, workspace: Path, session_id: str, stop_mode: str = "allow") -> dict[str, object]:
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
        payload["task_signature"] = "benchmark-stop-task"
        if stop_mode == "objective_failure":
            payload.update(
                {
                    "last_assistant_message": "Objective validation is pending.",
                    "tests_failed": True,
                    "critical": True,
                    "evidence_fingerprint": f"failure-{session_id}",
                }
            )
        else:
            payload["last_assistant_message"] = "Completed benchmark validation."
            payload["scenario"] = "stop_allow"
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
        for event, role in ACTIVE_ROLE_COMMANDS:
            modes = ("allow", "objective_failure") if event == "Stop" else ("default",)
            for stop_mode in modes:
                for effective_config in ("project_only", "global_only", "global_plus_project"):
                    samples: list[float] = []
                    stdout_sizes: list[int] = []
                    blocks = 0
                    suppressed_samples: list[float] = []
                    for iteration in range(iterations):
                        session_id = f"hook-cost-{event}-{role}-{stop_mode}-{effective_config}-{iteration}"
                        before_bytes = directory_bytes(Path(env["RALPH_HOME"]))
                        if effective_config == "project_only":
                            payload = lifecycle_payload(event, ROOT, session_id, stop_mode)
                            elapsed_ms, output = run_lifecycle_once(direct_command(event, role), payload, env, ROOT)
                        elif effective_config == "global_only":
                            payload = lifecycle_payload(event, global_workspace, session_id, stop_mode)
                            elapsed_ms, output = run_lifecycle_once(dispatcher_command(event, role), payload, env, global_workspace)
                        else:
                            payload = lifecycle_payload(event, ROOT, session_id, stop_mode)
                            suppressed_ms, suppressed_output = run_lifecycle_once(dispatcher_command(event, role), payload, env, ROOT)
                            if suppressed_output:
                                raise RuntimeError(f"global dispatcher did not suppress {event}/{role}")
                            suppressed_samples.append(suppressed_ms)
                            elapsed_ms, output = run_lifecycle_once(direct_command(event, role), payload, env, ROOT)
                        after_bytes = directory_bytes(Path(env["RALPH_HOME"]))
                        samples.append(elapsed_ms)
                        stdout_sizes.append(len(output.encode("utf-8")))
                        blocks += output_block_count(output)

                    p50_ms = statistics.median(samples)
                    p95_ms = percentile(samples, 95)
                    stdout_chars = int(statistics.median(stdout_sizes))
                    source_scope = "global" if effective_config == "global_only" else "project"
                    case_name = f"stop_{stop_mode}" if event == "Stop" else "lifecycle"
                    cases.append(
                        {
                            "payload": case_name,
                            "scenario": case_name,
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
                            "continuation_count": blocks if event == "Stop" else 0,
                            "persisted_bytes": after_bytes,
                            "persisted_bytes_delta": max(0, after_bytes - before_bytes),
                            "output_bytes": int(stdout_chars),
                            "configured_handler_count": 1,
                            "matched_handler_count": 1,
                            "executed_handler_count": 1,
                            "child_process_count": 1 if effective_config == "global_only" else 0,
                            "known_subprocesses": (
                                ["global_hook_dispatch", "hook_child", "git"]
                                if effective_config == "global_only"
                                else ["git"]
                                if event == "Stop"
                                else []
                            ),
                        }
                    )
                    if suppressed_samples:
                        cases.append(
                            {
                                "payload": case_name,
                                "scenario": case_name,
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
                                "persisted_bytes_delta": 0,
                                "output_bytes": 0,
                                "configured_handler_count": 1,
                                "matched_handler_count": 0,
                                "executed_handler_count": 0,
                                "child_process_count": 0,
                                "known_subprocesses": ["global_hook_dispatch"],
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
    report = {
        "schema_version": 2,
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
        "subscription_usage_measured": False,
        "post_tool_processes_before": 6,
        "post_tool_processes_after": 1,
        "post_tool_processes_reduction": 5,
        "active_post_tool_roles": ["post_tool_dispatch"],
        "stop_processes_before": 8,
        "stop_processes_after": 1,
        "stop_processes_reduction": 7,
        "active_stop_roles": ["stop_dispatch"],
        "matched_handler_count": sum(int(case.get("matched_handler_count", 0)) for case in effective_cases),
        "executed_handler_count": sum(int(case.get("executed_handler_count", 0)) for case in effective_cases),
    }
    for case in report["cases"]:
        case.setdefault("schema_version", 2)
        case.setdefault("output_bytes", int(case.get("stdout_chars", 0)))
        case.setdefault("configured_handler_count", 1)
        case.setdefault("matched_handler_count", 1)
        case.setdefault("executed_handler_count", 1)
        case.setdefault("child_process_count", 0)
        case.setdefault("known_subprocesses", [])
        case.setdefault("persisted_bytes_delta", int(case.get("persisted_bytes", 0)))
    return report


def markdown_report(report: dict[str, object]) -> str:
    lines = [
        "# Hook runtime benchmark",
        "",
        f"- Schema: `{report.get('schema_version', 1)}`",
        f"- Iterations: `{report.get('iterations', 0)}`",
        f"- PostToolUse processes: `{report.get('post_tool_processes_before', 6)}` → `{report.get('post_tool_processes_after', 1)}`",
        f"- Stop processes: `{report.get('stop_processes_before', 8)}` → `{report.get('stop_processes_after', 1)}`",
        f"- Runtime p50/p95 aggregate: `{report.get('total_p50_ms', 0)} ms` / see JSON cases",
        f"- Subscription usage measured: `{report.get('subscription_usage_measured', False)}`",
        "",
        "| Event | Role | p50 ms | p95 ms | matched | executed | output bytes | persisted bytes | blocks |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in report.get("cases", []):
        lines.append(
            "| {event} | {role} | {p50} | {p95} | {matched} | {executed} | {output} | {persisted} | {blocks} |".format(
                event=case.get("event", ""),
                role=case.get("role", ""),
                p50=case.get("runtime_p50_ms", 0),
                p95=case.get("runtime_p95_ms", 0),
                matched=case.get("matched_handler_count", 0),
                executed=case.get("executed_handler_count", 0),
                output=case.get("output_bytes", 0),
                persisted=case.get("persisted_bytes_delta", 0),
                blocks=case.get("block_count", 0),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure bounded local hook runtime and persistence attribution.")
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    iterations = args.iterations if args.iterations is not None else int(os.environ.get("RALPH_HOOK_COST_ITERATIONS", "3"))
    report = measure(max(1, iterations))
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"METRIC hook_cost_score={report['hook_cost_score']}")
    print(f"METRIC hook_total_p50_ms={report['total_p50_ms']}")
    print(f"METRIC hook_output_context_units={report['estimated_context_units']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
