from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
DISPATCHER = HOOKS / "global_hook_dispatch.py"
INSTALLER = ROOT / "scripts" / "setup" / "install-global-hooks.py"

ROLE_COMMANDS: dict[tuple[str, str], list[str]] = {
    ("SessionStart", "session_start_dispatch"): [sys.executable, str(HOOKS / "session_start_dispatch.py")],
    ("SessionStart", "session_start_wakeup"): [sys.executable, str(HOOKS / "session_start_wakeup.py")],
    ("UserPromptSubmit", "user_prompt_dispatch"): [sys.executable, str(HOOKS / "user_prompt_dispatch.py")],
    ("UserPromptSubmit", "universal_prompt_classifier"): ["bash", str(HOOKS / "universal-prompt-classifier.sh")],
    ("UserPromptSubmit", "sol_advisor_prompt_state"): [sys.executable, str(HOOKS / "sol_advisor_prompt_state.py")],
    ("UserPromptSubmit", "user_prompt_capture"): [sys.executable, str(HOOKS / "user_prompt_capture.py")],
    ("UserPromptSubmit", "user_prompt_improve"): [sys.executable, str(HOOKS / "user_prompt_improve.py")],
    ("UserPromptSubmit", "continuity_prompt_context"): [sys.executable, str(HOOKS / "continuity_prompt_context.py")],
    ("PreToolUse", "security_pre_tool_dispatch"): [sys.executable, str(HOOKS / "security_pre_tool_dispatch.py")],
    ("PreToolUse", "pre_tool_guard"): [sys.executable, str(HOOKS / "pre_tool_guard.py")],
    ("PostToolUse", "post_tool_dispatch"): [sys.executable, str(HOOKS / "post_tool_dispatch.py")],
    ("Stop", "stop_dispatch"): [sys.executable, str(HOOKS / "stop_dispatch.py")],
    ("Stop", "anti_rationalization_stop"): ["bash", str(HOOKS / "anti-rationalization-stop.sh")],
    ("Stop", "ralph_stop_quality_gate"): ["bash", str(HOOKS / "ralph-stop-quality-gate.sh")],
    ("Stop", "file_line_guard_stop"): [sys.executable, str(HOOKS / "file_line_guard.py"), "--event", "Stop"],
    ("Stop", "stop_route_decision_warn"): [sys.executable, str(HOOKS / "stop_route_decision_warn.py")],
    ("Stop", "implementation_notes_guard"): [sys.executable, str(HOOKS / "implementation_notes_guard.py")],
    ("Stop", "sol_advisor_stop_guard"): [sys.executable, str(HOOKS / "sol_advisor_stop_guard.py")],
    ("Stop", "stop_persist_memory"): [sys.executable, str(HOOKS / "stop_persist_memory.py")],
    ("Stop", "stop_memory_promotion_review"): [sys.executable, str(HOOKS / "stop_memory_promotion_review.py")],
}


def isolated_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(tmp_path / "ralph")
    env["CODEX_MEMORY_HOME"] = str(tmp_path / "codex-memory")
    env["VAULT_DIR"] = str(tmp_path / "vault")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    env["CODEX_HOOK_STATE_ROOT"] = str(tmp_path / "hook-state")
    env["CODEX_SLOP_GUARD_ENABLED"] = "0"
    return env


def payload_for(event: str, cwd: Path, session_id: str) -> dict[str, object]:
    base: dict[str, object] = {"hook_event_name": event, "cwd": str(cwd), "session_id": session_id}
    if event == "SessionStart":
        base["source"] = "startup"
    elif event == "UserPromptSubmit":
        base["prompt"] = "Review the hook context contract without changing unrelated files."
    elif event == "PreToolUse":
        base["tool_name"] = "exec_command"
        base["tool_input"] = {"cmd": "git status --short --branch", "workdir": str(cwd)}
    elif event == "PostToolUse":
        base["tool_name"] = "exec_command"
        base["tool_use_id"] = f"toolu_{session_id}"
        base["tool_input"] = {"cmd": "git status --short --branch", "workdir": str(cwd)}
        base["tool_response"] = {"exit_code": 0, "stdout": "## branch\n"}
        base["success"] = True
    elif event == "Stop":
        base["last_assistant_message"] = "Completed local hook validation."
    return base


def run(command: list[str], payload: dict[str, object], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def generated_global_config(tmp_path: Path) -> dict[str, object]:
    env = isolated_env(tmp_path)
    env["HOME"] = str(tmp_path / "home")
    result = subprocess.run(
        [sys.executable, str(INSTALLER), "--dry-run", "--allow-worktree-source"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout[result.stdout.find("{") :])


def configured_commands(config: dict[str, object], event: str) -> list[str]:
    hooks = config["hooks"]
    assert isinstance(hooks, dict)
    commands: list[str] = []
    for group in hooks.get(event, []):
        for hook in group["hooks"]:
            commands.append(hook["command"])
    return commands


def role_for_command(event: str, command: str) -> str:
    dispatcher = re.search(r"global_hook_dispatch\.py\s+--event\s+\S+\s+--role\s+([a-z_]+)", command)
    if dispatcher:
        return dispatcher.group(1)
    if "file_line_guard.py" in command:
        return "file_line_guard_post_tool" if event == "PostToolUse" else "file_line_guard_stop"
    for (_candidate_event, role), child in ROLE_COMMANDS.items():
        child_name = Path(child[1] if child[0] == "bash" else child[-1]).name
        if child_name in command:
            return role
    raise AssertionError(f"unrecognized configured hook command: {command}")


def roles_for_config(config: dict[str, object], event: str) -> list[str]:
    return [role_for_command(event, command) for command in configured_commands(config, event)]


def test_generated_global_config_has_the_same_semantic_roles_as_project(tmp_path: Path) -> None:
    project = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    global_config = generated_global_config(tmp_path)

    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        assert roles_for_config(global_config, event) == roles_for_config(project, event)
        assert all("global_hook_dispatch.py" in command for command in configured_commands(global_config, event))


def test_global_dispatcher_suppresses_every_project_equivalent(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    session_id = f"effective-chain-{uuid.uuid4()}"

    configured = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    configured_roles = {
        (event, role)
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
        for role in roles_for_config(configured, event)
    }
    for event, role in sorted(configured_roles):
        command = ROLE_COMMANDS[(event, role)]
        payload = payload_for(event, ROOT, session_id)
        global_result = run(
            [sys.executable, str(DISPATCHER), "--event", event, "--role", role],
            payload,
            ROOT,
            env,
        )
        assert global_result.returncode == 0, global_result.stderr
        assert global_result.stdout == "", f"{event}/{role} was not suppressed: {global_result.stdout}"

        project_result = run(command, payload, ROOT, env)
        assert project_result.returncode == 0, f"{event}/{role}: {project_result.stderr}"


def test_global_dispatcher_finds_project_config_from_nested_workdir(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    nested = ROOT / "tests" / "unit"
    payload = payload_for("PreToolUse", nested, "nested-project-suppression")
    payload["cwd"] = str(nested)
    payload["tool_input"] = {"cmd": "git status --short", "workdir": str(nested)}
    result = run(
        [sys.executable, str(DISPATCHER), "--event", "PreToolUse", "--role", "security_pre_tool_dispatch"],
        payload,
        nested,
        env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_global_dispatcher_falls_back_when_project_role_is_missing(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = payload_for("UserPromptSubmit", workspace, "fallback-session")

    fallback = run(
        [sys.executable, str(DISPATCHER), "--event", "UserPromptSubmit", "--role", "user_prompt_improve"],
        payload,
        workspace,
        env,
    )
    assert fallback.returncode == 0, fallback.stderr
    assert "Prompt contract:" in fallback.stdout

    (workspace / ".codex").mkdir()
    (workspace / ".codex" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {"hooks": [{"type": "command", "command": "python3 .codex/hooks/user_prompt_capture.py"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    suppressed = run(
        [sys.executable, str(DISPATCHER), "--event", "UserPromptSubmit", "--role", "user_prompt_capture"],
        payload,
        workspace,
        env,
    )
    assert suppressed.returncode == 0, suppressed.stderr
    assert suppressed.stdout == ""

    still_fallback = run(
        [sys.executable, str(DISPATCHER), "--event", "UserPromptSubmit", "--role", "user_prompt_improve"],
        payload,
        workspace,
        env,
    )
    assert still_fallback.returncode == 0, still_fallback.stderr
    assert "Prompt contract:" in still_fallback.stdout

    (workspace / ".codex" / "hooks.json").write_text("{invalid-json", encoding="utf-8")
    malformed_fallback = run(
        [sys.executable, str(DISPATCHER), "--event", "UserPromptSubmit", "--role", "user_prompt_improve"],
        payload,
        workspace,
        env,
    )
    assert malformed_fallback.returncode == 0, malformed_fallback.stderr
    assert "Prompt contract:" in malformed_fallback.stdout


def test_global_dispatcher_ignores_unknown_role(tmp_path: Path) -> None:
    result = run(
        [sys.executable, str(DISPATCHER), "--event", "Stop", "--role", "not_allowlisted"],
        payload_for("Stop", tmp_path, "unknown-role"),
        tmp_path,
        isolated_env(tmp_path),
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_effective_user_prompt_context_is_compact_and_nonduplicated(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    sentinel = "RAW_PROMPT_SENTINEL_52b2cc"
    payload = payload_for("UserPromptSubmit", ROOT, "prompt-contract")
    payload["prompt"] = f"{sentinel} review the hooks"
    outputs: list[str] = []
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))

    if "UserPromptSubmit" not in config.get("hooks", {}):
        pytest.skip("UserPromptSubmit lifecycle is intentionally disabled in #84 security-only profile")

    roles = roles_for_config(config, "UserPromptSubmit")
    assert roles == ["user_prompt_dispatch"]
    for role in roles:
        global_result = run(
            [sys.executable, str(DISPATCHER), "--event", "UserPromptSubmit", "--role", role],
            payload,
            ROOT,
            env,
        )
        assert global_result.returncode == 0, global_result.stderr
        assert global_result.stdout == ""
        result = run(ROLE_COMMANDS[("UserPromptSubmit", role)], payload, ROOT, env)
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)

    context = "".join(outputs)
    assert len(context.encode("utf-8")) <= 1800
    assert "Prompt classification:" in context
    assert "# Ralph Task Intake" in context
    assert "Prompt contract:" in context
    assert context.count("complexity=") == 1
    assert context.count("route=") == 1
    assert context.count("CLARIFICATION_REQUIRED=") == 1
    assert sentinel not in context

    repeated = run(ROLE_COMMANDS[("UserPromptSubmit", "user_prompt_dispatch")], payload, ROOT, env)
    assert repeated.returncode == 0, repeated.stderr
    assert repeated.stdout == ""
