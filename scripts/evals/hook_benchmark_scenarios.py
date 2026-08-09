"""Deterministic, isolated scenario runner for hook runtime attribution."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from hook_benchmark_config import configured_handler_counts, handler_specs


PROFILES = {
    "luna": ("gpt-5.6-luna", "luna"),
    "sol": ("gpt-5.6-sol", "sol"),
    "conservative_unknown": ("unknown-model", "unknown"),
}
SCENARIOS = (
    "small_read_only",
    "small_edit",
    "medium_edit_test",
    "repeated_prompt",
    "session_start_startup",
    "session_start_compact",
    "stop_allow",
    "stop_objective_failure",
    "subagent_route",
    "red_safety",
)


@dataclass(frozen=True)
class Step:
    event: str
    payload: dict[str, object]


@dataclass(frozen=True)
class Sample:
    runtime_ms: float
    output_bytes: int
    blocks: int
    continuations: int
    configured: int
    matched: int
    executed: int
    child_count: int | None
    cache_hits: int
    advisor_count: int
    persisted_delta: int
    events: tuple[str, ...]
    roles: tuple[str, ...]
    skipped_reasons: tuple[str, ...]
    components_considered: tuple[str, ...]
    components_executed: tuple[str, ...]
    components_skipped: tuple[str, ...]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("percentile requires one or more samples")
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[index]


def directory_bytes(path: Path, *, max_files: int = 4096) -> int:
    if not path.exists():
        return 0
    total = 0
    seen = 0
    for root, directories, files in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()]
        for name in files:
            candidate = Path(root) / name
            if candidate.is_symlink():
                continue
            seen += 1
            if seen > max_files:
                raise RuntimeError("benchmark persistence tree exceeded the bounded file count")
            try:
                total += candidate.stat().st_size
            except OSError as exc:
                raise RuntimeError("benchmark could not measure persisted bytes") from exc
    return total


def _base(event: str, workspace: Path, identity: str, model: str, scenario: str) -> dict[str, object]:
    return {
        "hook_event_name": event,
        "cwd": str(workspace),
        "workspace_root": str(workspace),
        "session_id": f"benchmark-{identity}",
        "turn_id": f"turn-{identity}",
        "branch": "benchmark-branch",
        "sha": "0123456789abcdef0123456789abcdef01234567",
        "model": model,
        "scenario": scenario,
    }


def _tool_steps(base: dict[str, object], name: str, data: dict[str, object], response: dict[str, object]) -> list[Step]:
    invocation = f"call-{base['session_id']}-{len(name)}"
    before = {**base, "hook_event_name": "PreToolUse", "tool_name": name, "tool_input": data}
    after = {
        **base,
        "hook_event_name": "PostToolUse",
        "tool_name": name,
        "tool_use_id": invocation,
        "tool_input": data,
        "tool_response": response,
        "success": int(response.get("exit_code", 0)) == 0,
    }
    return [Step("PreToolUse", before), Step("PostToolUse", after)]


def scenario_steps(scenario: str, profile: str, workspace: Path, identity: str) -> list[Step]:
    model, _family = PROFILES[profile]
    base = _base("", workspace, identity, model, scenario)
    if scenario == "small_read_only":
        return _tool_steps(base, "exec_command", {"cmd": "git status --short", "workdir": str(workspace)}, {"exit_code": 0, "stdout": ""})
    if scenario in {"small_edit", "medium_edit_test"}:
        target = "notes.md" if scenario == "small_edit" else "src/example.py"
        patch = f"*** Begin Patch\n*** Update File: {target}\n@@\n-old\n+new\n*** End Patch"
        steps = _tool_steps(
            base,
            "apply_patch",
            {"patch": patch, "workdir": str(workspace)},
            {"exit_code": 0, "stdout": "Done", "changed_files": [target]},
        )
        if scenario == "medium_edit_test":
            test_base = {**base, "turn_id": f"test-{identity}"}
            steps.extend(
                _tool_steps(
                    test_base,
                    "exec_command",
                    {"cmd": "pytest tests/unit/test_fixture.py -q", "workdir": str(workspace)},
                    {"exit_code": 0, "stdout": "1 passed"},
                )
            )
        return steps
    if scenario == "repeated_prompt":
        prompt = "Review the effective hook pipeline and preserve all objective safety gates."
        payload = {**base, "hook_event_name": "UserPromptSubmit", "prompt": prompt, "memory_generation": "generation-a"}
        return [Step("UserPromptSubmit", dict(payload)), Step("UserPromptSubmit", dict(payload))]
    if scenario.startswith("session_start_"):
        source = scenario.removeprefix("session_start_")
        payload = {
            **base,
            "hook_event_name": "SessionStart",
            "source": source,
            "task_signature": f"task-{identity}",
            "objective": "Preserve objective hook safety gates.",
            "pending_validation": ["unit-tests"],
            "selected_memory_ids": ["benchmark-memory-sentinel"],
        }
        return [Step("SessionStart", payload)]
    if scenario.startswith("stop_"):
        payload = {
            **base,
            "hook_event_name": "Stop",
            "task_signature": f"task-{identity}",
            "last_assistant_message": "Benchmark fixture completed.",
            "verified_done": scenario == "stop_allow",
        }
        if scenario == "stop_objective_failure":
            payload.update(
                {
                    "tests_failed": True,
                    "critical": True,
                    "evidence_fingerprint": f"failure-{identity}",
                    "last_assistant_message": "Objective test failed in the current task scope.",
                }
            )
        return [Step("Stop", payload)]
    if scenario == "subagent_route":
        payload = {
            **base,
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "complexity": 7,
            "task_signature": f"task-{identity}",
            "tool_input": {
                "agent_type": "explorer",
                "task_name": "benchmark_route",
                "fork_turns": "none",
                "message": "Inspect one bounded fixture and return evidence only.",
                "invocation_id": f"spawn-{identity}",
            },
        }
        return [Step("PreToolUse", payload)]
    if scenario == "red_safety":
        protected_name = "api_" + "key"
        protected_value = protected_name + "=fixture-sensitive-value"
        payload = {
            **base,
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__remote__send",
            "sensitivity": "RED",
            "tool_input": {"message": protected_value},
        }
        return [Step("PreToolUse", payload)]
    raise ValueError(f"unknown benchmark scenario: {scenario}")


def _isolated_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_HOME": str(root / "runtime"),
            "CODEX_HOOK_STATE_ROOT": str(root / "hook-state"),
            "CODEX_MEMORY_HOME": str(root / "memory-empty"),
            "VAULT_DIR": str(root / "vault-empty"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "RALPH_SCAFFOLD_PROFILE": "auto",
        }
    )
    env.pop("RALPH_MEMORY_TRACE", None)
    return env


def _runtime_events(runtime_root: Path, scenario: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    accepted_scenarios = {scenario}
    if scenario.startswith("session_start_"):
        accepted_scenarios.add(scenario.removeprefix("session_start_"))
    for path in sorted(runtime_root.glob("projects/*/observability/runtime-events.jsonl*")):
        if path.is_symlink() or not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError("benchmark runtime event stream is corrupt") from exc
            if isinstance(value, dict) and value.get("scenario") in accepted_scenarios:
                events.append(value)
    return events


def _block(output: str, event: str) -> bool:
    if not output.strip():
        return False
    if event == "SessionStart":
        return False
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("hook emitted non-JSON stdout") from exc
    return isinstance(value, dict) and value.get("decision") == "block"


def run_sample(config: Mapping[str, object], root: Path, scenario: str, profile: str, identity: str) -> Sample:
    temporary_root = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix="ralph-hook-scenario-", dir=temporary_root) as temporary:
        case_root = Path(temporary)
        workspace = case_root / "workspace"
        (workspace / "src").mkdir(parents=True)
        (workspace / "notes.md").write_text("old\n", encoding="utf-8")
        (workspace / "src" / "example.py").write_text("old\n" * 180, encoding="utf-8")
        env = _isolated_env(case_root)
        runtime_root = Path(env["RALPH_HOME"])
        before = directory_bytes(runtime_root)
        configured_counts = configured_handler_counts(config)
        steps = scenario_steps(scenario, profile, workspace, identity)
        configured = sum(configured_counts.get(event, 0) for event in {step.event for step in steps})
        matched = executed = output_bytes = blocks = continuations = 0
        roles: list[str] = []
        started = time.perf_counter_ns()
        for step in steps:
            specs = handler_specs(config, step.event, step.payload, root=root)
            matched += len(specs)
            for spec in specs:
                completed = subprocess.run(
                    list(spec.command),
                    cwd=workspace,
                    input=json.dumps(step.payload),
                    text=True,
                    capture_output=True,
                    env=env,
                    check=False,
                    timeout=max(2.0, min(spec.timeout + 2.0, 30.0)),
                )
                if completed.returncode != 0:
                    raise RuntimeError(f"benchmark handler failed: {step.event}/{spec.role} exit={completed.returncode}")
                executed += 1
                roles.append(spec.role)
                output_bytes += len(completed.stdout.encode("utf-8"))
                blocked = _block(completed.stdout, step.event)
                blocks += int(blocked)
                continuations += int(blocked and step.event == "Stop")
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        events = _runtime_events(runtime_root, scenario)
        child_count = sum(int(event.get("child_process_count", 0)) for event in events) if events else None
        cache_hits = sum(1 for event in events if event.get("cache_hit") is True)
        advisor_count = sum(int(event.get("advisor_count", 0)) for event in events)
        def event_codes(field: str) -> tuple[str, ...]:
            values = [
                str(value)
                for event in events
                for value in (event.get(field) if isinstance(event.get(field), list) else [])
            ]
            return tuple(dict.fromkeys(values))
        persisted = max(0, directory_bytes(runtime_root) - before)
        return Sample(
            runtime_ms=elapsed_ms,
            output_bytes=output_bytes,
            blocks=blocks,
            continuations=continuations,
            configured=configured,
            matched=matched,
            executed=executed,
            child_count=child_count,
            cache_hits=cache_hits,
            advisor_count=advisor_count,
            persisted_delta=persisted,
            events=tuple(dict.fromkeys(step.event for step in steps)),
            roles=tuple(dict.fromkeys(roles)),
            skipped_reasons=event_codes("skipped_reason"),
            components_considered=event_codes("components_considered"),
            components_executed=event_codes("components_executed"),
            components_skipped=event_codes("components_skipped"),
        )


__all__ = ["PROFILES", "SCENARIOS", "Sample", "directory_bytes", "percentile", "run_sample", "scenario_steps"]
