#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


GLOBAL_HOOK_DIR = Path.home() / ".codex" / "hooks"
GLOBAL_HOOKS_JSON = Path.home() / ".codex" / "hooks.json"


def run_hook(name: str, payload: dict, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GLOBAL_HOOK_DIR / name)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=os.environ.copy() | env,
        check=False,
    )


def run_hook_command(command: str, payload: dict, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        shlex.split(command),
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=os.environ.copy() | env,
        check=False,
    )


def assert_ok(label: str, result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed: {result.stderr or result.stdout}")


def assert_stop_output_contract(label: str, result: subprocess.CompletedProcess[str]) -> None:
    assert_hook_output_contract("Stop", label, result)


def assert_hook_output_contract(event: str, label: str, result: subprocess.CompletedProcess[str]) -> None:
    assert_ok(label, result)
    output = result.stdout.strip()
    if not output:
        return
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        if event in {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}:
            return
        raise RuntimeError(f"{label} emitted invalid plain stdout: {output[:200]}") from exc
    decision = payload.get("decision")
    if decision is not None:
        if decision != "block" or not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
            raise RuntimeError(f"{label} emitted unsupported decision payload: {output[:200]}")
    if event == "PreToolUse" and any(key in payload for key in ("continue", "stopReason", "suppressOutput")):
        raise RuntimeError(f"{label} emitted unsupported PreToolUse common output: {output[:200]}")
    if event == "PostToolUse":
        if payload.get("decision") == "warn":
            raise RuntimeError(f"{label} emitted unsupported PostToolUse warn payload: {output[:200]}")
        if payload.get("continue") is True or "suppressOutput" in payload:
            raise RuntimeError(f"{label} emitted unsupported PostToolUse common output: {output[:200]}")


def hook_basenames(config: dict, event: str) -> list[str]:
    names: list[str] = []
    for group in config.get("hooks", {}).get(event, []):
        for hook in group.get("hooks", []):
            matches = re.findall(r"([A-Za-z0-9_.-]+\.(?:py|sh))", str(hook.get("command", "")))
            if matches:
                names.append(matches[-1])
    return names


def hook_commands(config: dict, event: str) -> list[str]:
    commands: list[str] = []
    for group in config.get("hooks", {}).get(event, []):
        for hook in group.get("hooks", []):
            command = hook.get("command")
            if isinstance(command, str) and command.strip():
                commands.append(command)
    return commands


def init_git(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def one_match(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        raise RuntimeError(f"{label} expected one match, found {len(paths)}")
    return paths[0]


def main() -> int:
    if not GLOBAL_HOOKS_JSON.is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {GLOBAL_HOOKS_JSON}", file=sys.stderr)
        return 1
    config = json.loads(GLOBAL_HOOKS_JSON.read_text(encoding="utf-8"))
    required = {
        "SessionStart": ["session_start_wakeup.py"],
        "UserPromptSubmit": ["user_prompt_capture.py", "continuity_prompt_context.py"],
        "PreToolUse": ["pre_tool_guard.py"],
        "PostToolUse": [
            "file_line_guard.py",
            "shaping_ripple.py",
            "post_tool_extract_memory.py",
            "post_tool_checkpoint.py",
            "post_tool_cost_ledger.py",
        ],
        "Stop": ["stop_persist_memory.py", "stop_memory_promotion_review.py"],
    }
    for event, names in required.items():
        sequence = hook_basenames(config, event)
        missing = [name for name in names if name not in sequence]
        if missing:
            print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {event} hooks {missing}", file=sys.stderr)
            return 1
    repo_root_file = GLOBAL_HOOK_DIR / ".ralph-repo-root"
    if not repo_root_file.is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {repo_root_file}", file=sys.stderr)
        return 1
    repo_root = Path(repo_root_file.read_text(encoding="utf-8").strip())
    if not (repo_root / "scripts" / "memory" / "wakeup.py").is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL invalid repo root {repo_root}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        env = {
            "RALPH_HOME": str(base / "ralph"),
            "CODEX_MEMORY_HOME": str(base / "empty-codex-memory"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_SESSION_ID": "global-hook-smoke",
        }
        project_a = base / "project-a"
        project_b = base / "project-b"
        init_git(project_a)
        init_git(project_b)
        prompt = run_hook(
            "continuity_prompt_context.py",
            {
                "session_id": "global-hook-smoke",
                "cwd": str(project_a),
                "prompt": "Implement global hook smoke validation.",
            },
            env,
        )
        assert_ok("continuity_prompt_context.py", prompt)
        checkpoint_path = one_match(sorted(Path(env["RALPH_HOME"]).glob("projects/*/checkpoints/latest.json")), "project checkpoint")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint["objective"] != "Implement global hook smoke validation.":
            raise RuntimeError("prompt checkpoint objective mismatch")
        if checkpoint["project"] != "project-a":
            raise RuntimeError("prompt checkpoint project mismatch")

        wrong_project = run_hook(
            "continuity_prompt_context.py",
            {"session_id": "global-hook-smoke-b", "cwd": str(project_b), "prompt": "continua"},
            env,
        )
        assert_ok("continuity_prompt_context.py project-b", wrong_project)
        if wrong_project.stdout.strip():
            raise RuntimeError("project-b received project-a checkpoint")

        post_tool = run_hook(
            "post_tool_checkpoint.py",
            {
                "cwd": str(project_a),
                "tool_input": {"command": "python3 -m pytest tests/integration/test_hook_lifecycle_e2e.py"},
                "success": True,
            },
            env,
        )
        assert_ok("post_tool_checkpoint.py", post_tool)
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint["validation_status"] != "pass":
            raise RuntimeError("post tool checkpoint did not mark validation pass")

        wakeup = run_hook("session_start_wakeup.py", {"cwd": str(project_a)}, env)
        assert_ok("session_start_wakeup.py", wakeup)
        if "Latest Rolling Checkpoint" not in wakeup.stdout:
            raise RuntimeError("session start did not include rolling checkpoint")

        stale_wakeup = run_hook(
            "pre_tool_guard.py",
            {"tool_input": {"command": "python3 scripts/memory/wakeup.py", "workdir": str(project_a)}},
            env,
        )
        assert_ok("pre_tool_guard.py stale wakeup", stale_wakeup)
        if '"decision": "block"' not in stale_wakeup.stdout or "repo-local Ralph wakeup" not in stale_wakeup.stdout:
            raise RuntimeError("pre_tool_guard did not block stale repo-local wakeup")

        stop = run_hook(
            "stop_persist_memory.py",
            {"cwd": str(project_a), "last_assistant_message": "Global hook smoke finished."},
            env,
        )
        assert_ok("stop_persist_memory.py", stop)
        handoff_path = one_match(sorted(Path(env["RALPH_HOME"]).glob("projects/*/handoffs/latest.md")), "project handoff")
        handoff = handoff_path.read_text(encoding="utf-8")
        if "## Rolling Checkpoint" not in handoff:
            raise RuntimeError("stop handoff missing rolling checkpoint")

        stop_payload = {
            "session_id": "global-hook-smoke-stop-contract",
            "cwd": str(project_a),
            "last_assistant_message": "Smoke done.",
        }
        for index, command in enumerate(hook_commands(config, "Stop")):
            stop_result = run_hook_command(command, stop_payload, env)
            assert_stop_output_contract(f"Stop hook {index} {command}", stop_result)

        shaping_doc = project_a / "shaping.md"
        shaping_doc.write_text("---\nshaping: true\n---\n# Smoke shaping\n", encoding="utf-8")
        event_payloads = {
            "SessionStart": {"session_id": "global-hook-smoke-contract", "cwd": str(project_a), "source": "startup"},
            "UserPromptSubmit": {
                "session_id": "global-hook-smoke-contract",
                "cwd": str(project_a),
                "prompt": "Validate global hook contracts.",
            },
            "PreToolUse": {
                "session_id": "global-hook-smoke-contract",
                "cwd": str(project_a),
                "tool_name": "exec_command",
                "tool_input": {"cmd": "git status --short --branch", "workdir": str(project_a)},
            },
            "PostToolUse": {
                "session_id": "global-hook-smoke-contract",
                "cwd": str(project_a),
                "tool_name": "apply_patch",
                "tool_input": {"path": str(shaping_doc), "cwd": str(project_a)},
                "tool_response": {"status": "ok"},
                "success": True,
            },
        }
        for event, payload in event_payloads.items():
            for index, command in enumerate(hook_commands(config, event)):
                result = run_hook_command(command, {"hook_event_name": event, **payload}, env)
                assert_hook_output_contract(event, f"{event} hook {index} {command}", result)

    print(f"GLOBAL_HOOKS_SMOKE_PASS repo={repo_root}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"GLOBAL_HOOKS_SMOKE_FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
