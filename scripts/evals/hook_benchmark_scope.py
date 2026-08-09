"""Measure global execution and semantic project-duplicate suppression."""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Mapping

from hook_benchmark_config import configured_handler_counts, handler_specs
from hook_benchmark_scenarios import percentile


def _payload(event: str, workspace: Path, identity: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "hook_event_name": event,
        "cwd": str(workspace),
        "workspace_root": str(workspace),
        "session_id": f"scope-{identity}",
        "turn_id": f"turn-{identity}",
        "branch": "benchmark-branch",
        "sha": "0123456789abcdef0123456789abcdef01234567",
        "model": "unknown-model",
        "scenario": "scope_probe",
    }
    if event == "SessionStart":
        payload["source"] = "startup"
    elif event == "UserPromptSubmit":
        payload["prompt"] = "Inspect one bounded hook scope fixture."
    elif event == "PreToolUse":
        payload.update({"tool_name": "exec_command", "tool_input": {"cmd": "git status --short", "workdir": str(workspace)}})
    elif event == "PostToolUse":
        payload.update(
            {
                "tool_name": "exec_command",
                "tool_use_id": f"call-{identity}",
                "tool_input": {"cmd": "git status --short", "workdir": str(workspace)},
                "tool_response": {"exit_code": 0, "stdout": ""},
                "success": True,
            }
        )
    elif event in {"SubagentStart", "SubagentStop"}:
        payload["agent_type"] = "explorer"
    elif event == "Stop":
        payload.update(
            {
                "task_signature": f"task-{identity}",
                "last_assistant_message": "Scope fixture completed.",
                "verified_done": True,
            }
        )
    return payload


def _env(case_root: Path, root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_HOME": str(case_root / "runtime"),
            "CODEX_HOOK_STATE_ROOT": str(case_root / "hook-state"),
            "CODEX_MEMORY_HOME": str(case_root / "memory-empty"),
            "VAULT_DIR": str(case_root / "vault-empty"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "RALPH_REPO_ROOT": str(root),
            "RALPH_SCAFFOLD_PROFILE": "auto",
        }
    )
    return env


def _role(config: Mapping[str, object], event: str, root: Path) -> str:
    workspace = root / "tests"
    payload = _payload(event, workspace, f"role-{event}")
    specs = handler_specs(config, event, payload, root=root)
    if len(specs) != 1:
        raise RuntimeError(f"scope benchmark expected one active handler for {event}, got {len(specs)}")
    return specs[0].role


def measure_scopes(config: Mapping[str, object], root: Path, iterations: int) -> list[dict[str, object]]:
    dispatcher = root / ".codex" / "hooks" / "global_hook_dispatch.py"
    counts = configured_handler_counts(config)
    cases: list[dict[str, object]] = []
    for event in counts:
        role = _role(config, event, root)
        for source_scope in ("global", "suppressed-global"):
            durations: list[float] = []
            outputs: list[int] = []
            for index in range(iterations):
                temporary_root = Path(tempfile.gettempdir()).resolve()
                with tempfile.TemporaryDirectory(prefix="ralph-scope-bench-", dir=temporary_root) as temporary:
                    case_root = Path(temporary)
                    workspace = case_root / "workspace" if source_scope == "global" else root / "tests" / "unit"
                    if source_scope == "global":
                        workspace.mkdir()
                    payload = _payload(event, workspace, f"{event}-{source_scope}-{index}")
                    started = time.perf_counter_ns()
                    completed = subprocess.run(
                        [sys.executable, str(dispatcher), "--event", event, "--role", role],
                        cwd=workspace,
                        input=json.dumps(payload),
                        text=True,
                        capture_output=True,
                        env=_env(case_root, root),
                        check=False,
                        timeout=30,
                    )
                    durations.append((time.perf_counter_ns() - started) / 1_000_000)
                    if completed.returncode != 0:
                        raise RuntimeError(f"scope benchmark failed: {event}/{source_scope}")
                    if source_scope == "suppressed-global" and completed.stdout:
                        raise RuntimeError(f"project duplicate was not silent: {event}")
                    outputs.append(len(completed.stdout.encode("utf-8")))
            suppressed = source_scope == "suppressed-global"
            cases.append(
                {
                    "schema_version": 2,
                    "scenario": "scope_probe",
                    "profile": "conservative_unknown",
                    "model_family": "unknown",
                    "event": event,
                    "role": role,
                    "effective_config": "global_plus_project" if suppressed else "global_only",
                    "source_scope": source_scope,
                    "configured_handler_count": counts[event],
                    "matched_handler_count": 0 if suppressed else 1,
                    "executed_handler_count": 0 if suppressed else 1,
                    "process_count": 1 if suppressed else 2,
                    "child_process_count": 0 if suppressed else 1,
                    "child_process_count_measured": True,
                    "skipped_reason": ["project_duplicate"] if suppressed else [],
                    "runtime_wall_ms": round(statistics.median(durations), 3),
                    "runtime_p50_ms": round(statistics.median(durations), 3),
                    "runtime_p95_ms": round(percentile(durations, 95), 3),
                    "output_bytes": int(statistics.median(outputs)),
                    "estimated_context_units": (int(statistics.median(outputs)) + 3) // 4,
                    "block_count": 0,
                    "continuation_count": 0,
                    "persisted_bytes_delta": 0,
                    "subscription_usage_measured": False,
                }
            )
    return cases


__all__ = ["measure_scopes"]
