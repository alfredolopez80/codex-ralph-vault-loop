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
SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]


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
        extra = set(payload) - {"decision", "reason", "systemMessage", "continue", "stopReason", "hookSpecificOutput"}
        if extra:
            raise RuntimeError(f"{label} emitted unsupported PostToolUse fields {sorted(extra)}: {output[:200]}")
        if payload.get("decision") == "warn":
            raise RuntimeError(f"{label} emitted unsupported PostToolUse warn payload: {output[:200]}")
        if payload.get("continue") is True or "suppressOutput" in payload:
            raise RuntimeError(f"{label} emitted unsupported PostToolUse common output: {output[:200]}")
    if event == "Stop":
        extra = set(payload) - {"decision", "reason", "continue", "stopReason", "systemMessage", "suppressOutput"}
        if extra:
            raise RuntimeError(f"{label} emitted unsupported Stop fields {sorted(extra)}: {output[:200]}")


def check_project_mcp_config() -> None:
    checker = SCRIPT_REPO_ROOT / "scripts" / "model-router" / "check_mcp_config.py"
    config = SCRIPT_REPO_ROOT / ".codex" / "config.toml"
    migration = SCRIPT_REPO_ROOT / "docs" / "migration" / "mcp-tool-names.md"
    result = subprocess.run(
        [sys.executable, str(checker), "--config", str(config), "--migration-doc", str(migration), "--json"],
        cwd=SCRIPT_REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"MCP config audit failed: {result.stderr or result.stdout}")


def hook_roles(config: dict, event: str) -> list[str]:
    names: list[str] = []
    for group in config.get("hooks", {}).get(event, []):
        for hook in group.get("hooks", []):
            command = str(hook.get("command", ""))
            dispatcher = re.search(r"global_hook_dispatch\.py\s+--event\s+\S+\s+--role\s+([a-z_]+)", command)
            if dispatcher:
                names.append(dispatcher.group(1))
                continue
            if "file_line_guard.py" in command:
                names.append("file_line_guard_post_tool" if event == "PostToolUse" else "file_line_guard_stop")
                continue
            matches = re.findall(r"([A-Za-z0-9_.-]+\.(?:py|sh))", command)
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


def validate_codex_hook_schema(config: dict) -> None:
    """Catch schema-invalid numeric fields before executing any hook."""
    for event, groups in config.get("hooks", {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                timeout = hook.get("timeout")
                if type(timeout) is not int or timeout <= 0:
                    raise RuntimeError(
                        f"{event} timeout must be a positive integer, got {type(timeout).__name__}"
                    )
                context_limit = hook.get("additionalContextLimit")
                if context_limit is not None and (type(context_limit) is not int or context_limit < 0):
                    raise RuntimeError(
                        f"{event} additionalContextLimit must be an unsigned integer, "
                        f"got {type(context_limit).__name__}"
                    )


def init_git(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def one_match(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        raise RuntimeError(f"{label} expected one match, found {len(paths)}")
    return paths[0]


def _legacy_lifecycle_main() -> int:
    try:
        check_project_mcp_config()
    except RuntimeError as exc:
        print(f"GLOBAL_HOOKS_SMOKE_FAIL {exc}", file=sys.stderr)
        return 1
    if not GLOBAL_HOOKS_JSON.is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {GLOBAL_HOOKS_JSON}", file=sys.stderr)
        return 1
    config = json.loads(GLOBAL_HOOKS_JSON.read_text(encoding="utf-8"))
    validate_codex_hook_schema(config)
    required = {
        "SessionStart": ["session_start_dispatch"],
        "UserPromptSubmit": ["user_prompt_dispatch"],
        "PreToolUse": ["pre_tool_dispatch"],
        "PostToolUse": ["post_tool_dispatch"],
        "SubagentStart": ["sol_advisor_subagent_context"],
        "SubagentStop": ["sol_advisor_subagent_stop"],
        "Stop": ["stop_dispatch"],
    }
    for event, names in required.items():
        sequence = hook_roles(config, event)
        missing = [name for name in names if name not in sequence]
        if missing:
            print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {event} hooks {missing}", file=sys.stderr)
            return 1
        positions = [sequence.index(name) for name in names]
        if positions != sorted(positions):
            print(f"GLOBAL_HOOKS_SMOKE_FAIL invalid {event} hook order {sequence}", file=sys.stderr)
            return 1
    repo_root_file = GLOBAL_HOOK_DIR / ".ralph-repo-root"
    if not repo_root_file.is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {repo_root_file}", file=sys.stderr)
        return 1
    repo_root = Path(repo_root_file.read_text(encoding="utf-8").strip())
    if not (repo_root / "scripts" / "memory" / "wakeup.py").is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL invalid repo root {repo_root}", file=sys.stderr)
        return 1
    for required in (
        repo_root / ".codex" / "hooks" / "session_start_dispatch.py",
        repo_root / ".codex" / "hooks" / "memory_maintenance_enqueue.py",
        repo_root / "scripts" / "memory" / "run-pending-maintenance.py",
    ):
        if not required.is_file():
            print(f"GLOBAL_HOOKS_SMOKE_FAIL missing maintenance source {required}", file=sys.stderr)
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
        improve_sentinel = "GLOBAL_SMOKE_RAW_PROMPT_SENTINEL_61927"
        improve = run_hook(
            "user_prompt_improve.py",
            {"hook_event_name": "UserPromptSubmit", "prompt": improve_sentinel},
            env,
        )
        assert_ok("user_prompt_improve.py", improve)
        if len(improve.stdout.encode("utf-8")) > 768:
            raise RuntimeError("user_prompt_improve.py exceeded compact output budget")
        improve_payload = json.loads(improve.stdout)
        expected_context = improve_payload.get("hookSpecificOutput", {})
        if expected_context.get("hookEventName") != "UserPromptSubmit":
            raise RuntimeError("user_prompt_improve.py emitted unsupported hook event")
        if "Prompt contract:" not in str(expected_context.get("additionalContext", "")):
            raise RuntimeError("user_prompt_improve.py omitted compact prompt contract")
        if improve_sentinel in improve.stdout:
            raise RuntimeError("user_prompt_improve.py echoed the raw prompt")
        if Path(env["RALPH_HOME"]).exists():
            raise RuntimeError("user_prompt_improve.py persisted runtime state")
        empty_improve = run_hook(
            "user_prompt_improve.py",
            {"hook_event_name": "UserPromptSubmit", "prompt": "  "},
            env,
        )
        assert_ok("user_prompt_improve.py empty prompt", empty_improve)
        if empty_improve.stdout:
            raise RuntimeError("user_prompt_improve.py emitted context for an empty prompt")
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
        objective = str(checkpoint.get("objective", ""))
        if not objective.startswith("Task metadata: intent=code_change prompt_hash="):
            raise RuntimeError("prompt checkpoint safe objective metadata mismatch")
        if "Implement global hook smoke validation." in checkpoint_path.read_text(encoding="utf-8"):
            raise RuntimeError("prompt checkpoint persisted the raw prompt")
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
            "post_tool_dispatch.py",
            {
                "cwd": str(project_a),
                "tool_input": {"command": "python3 -m pytest tests/integration/test_hook_lifecycle_e2e.py"},
                "success": True,
            },
            env,
        )
        assert_ok("post_tool_dispatch.py", post_tool)
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint["validation_status"] != "pass":
            raise RuntimeError("post tool checkpoint did not mark validation pass")

        wakeup = run_hook("session_start_wakeup.py", {"cwd": str(project_a)}, env)
        assert_ok("session_start_wakeup.py", wakeup)
        if "Latest Rolling Checkpoint" not in wakeup.stdout:
            raise RuntimeError("session start did not include rolling checkpoint")

        stale_wakeup = run_hook(
            "pre_tool_dispatch.py",
            {"hook_event_name": "PreToolUse", "cwd": str(project_a), "tool_name": "exec_command",
             "tool_input": {"cmd": "python3 scripts/memory/wakeup.py", "workdir": str(project_a)}},
            env,
        )
        assert_ok("pre_tool_dispatch.py stale wakeup", stale_wakeup)
        if '"decision":"block"' not in stale_wakeup.stdout or "repo-local Ralph wakeup" not in stale_wakeup.stdout:
            raise RuntimeError("pre_tool_dispatch did not block stale repo-local wakeup")

        stop = run_hook(
            "stop_dispatch.py",
            {"cwd": str(project_a), "last_assistant_message": "Global hook smoke finished."},
            env,
        )
        assert_ok("stop_dispatch.py", stop)
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
        large_file = project_a / "large.py"
        large_file.write_text("x\n" * 351, encoding="utf-8")
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

        post_tool_large_payload = {
            "hook_event_name": "PostToolUse",
            "session_id": "global-hook-smoke-contract-large",
            "cwd": str(project_a),
            "tool_name": "apply_patch",
            "tool_input": {"path": str(large_file), "cwd": str(project_a)},
            "tool_response": {"status": "ok"},
            "success": True,
        }
        for index, command in enumerate(hook_commands(config, "PostToolUse")):
            result = run_hook_command(command, post_tool_large_payload, env)
            assert_hook_output_contract("PostToolUse", f"PostToolUse large hook {index} {command}", result)

    print(f"GLOBAL_HOOKS_SMOKE_PASS repo={repo_root}")
    return 0


def main() -> int:
    """Smoke only the active security-only global registration."""
    try:
        check_project_mcp_config()
    except RuntimeError as exc:
        print(f"GLOBAL_HOOKS_SMOKE_FAIL {exc}", file=sys.stderr)
        return 1
    if not GLOBAL_HOOKS_JSON.is_file():
        print(f"GLOBAL_HOOKS_SMOKE_FAIL missing {GLOBAL_HOOKS_JSON}", file=sys.stderr)
        return 1

    config = json.loads(GLOBAL_HOOKS_JSON.read_text(encoding="utf-8"))
    validate_codex_hook_schema(config)
    if set(config.get("hooks", {})) != {"PreToolUse"}:
        raise RuntimeError("global hooks are not security-only")
    if hook_roles(config, "PreToolUse") != ["security_pre_tool_dispatch"]:
        raise RuntimeError("global PreToolUse role is not security_pre_tool_dispatch")

    repo_root_file = GLOBAL_HOOK_DIR / ".ralph-repo-root"
    if not repo_root_file.is_file():
        raise RuntimeError(f"missing {repo_root_file}")
    repo_root = Path(repo_root_file.read_text(encoding="utf-8").strip())
    for required_source in (
        repo_root / ".codex" / "hooks" / "global_hook_dispatch.py",
        repo_root / ".codex" / "hooks" / "security_pre_tool_dispatch.py",
        repo_root / ".codex" / "hooks" / "pre_tool_guard.py",
        repo_root / "config" / "security-baseline.toml",
    ):
        if not required_source.is_file():
            raise RuntimeError(f"missing security-only source {required_source}")

    command = hook_commands(config, "PreToolUse")[0]
    with tempfile.TemporaryDirectory() as temp:
        workspace = Path(temp).resolve()
        env = {
            "RALPH_HOME": str(workspace / "ralph"),
            "CODEX_MEMORY_HOME": str(workspace / "empty-memory"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
        }
        blocked = run_hook_command(
            command,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(workspace),
                "tool_name": "exec_command",
                "tool_input": {"cmd": "git reset --hard HEAD"},
            },
            env,
        )
        assert_hook_output_contract("PreToolUse security negative", command, blocked)
        if json.loads(blocked.stdout).get("decision") != "block":
            raise RuntimeError("global security hook did not block the synthetic destructive command")

        allowed = run_hook_command(
            command,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(workspace),
                "tool_name": "exec_command",
                "tool_input": {"cmd": "git status --short"},
            },
            env,
        )
        assert_hook_output_contract("PreToolUse security harmless", command, allowed)
        if allowed.stdout.strip():
            raise RuntimeError("global security hook blocked the synthetic harmless command")

    baseline = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "gates" / "security-baseline.py")],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if baseline.returncode != 0 or '"passed": true' not in baseline.stdout:
        raise RuntimeError("SECURITY_BASELINE synthetic suite failed")

    print(f"GLOBAL_HOOKS_SMOKE_PASS security-only repo={repo_root}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"GLOBAL_HOOKS_SMOKE_FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
