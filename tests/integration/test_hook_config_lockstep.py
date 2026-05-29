from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "setup" / "install-global-hooks.py"


def hook_pairs(config: dict, event: str) -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for group in config["hooks"].get(event, []):
        for hook in group.get("hooks", []):
            command = str(hook.get("command", ""))
            matches = re.findall(r"([A-Za-z0-9_.-]+\.(?:py|sh))", command)
            pairs.append((matches[-1] if matches else command, int(hook.get("timeout", 0))))
    return pairs


def hook_commands(config: dict, event: str) -> list[str]:
    commands: list[str] = []
    for group in config["hooks"].get(event, []):
        for hook in group.get("hooks", []):
            command = hook.get("command")
            if isinstance(command, str) and command.strip():
                commands.append(command)
    return commands


def generated_global_config(home: Path) -> dict:
    env = os.environ.copy()
    env["HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    json_start = result.stdout.find("{")
    assert json_start >= 0, result.stdout
    return json.loads(result.stdout[json_start:])


def run_configured_hook(command: str, tmp_path: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(tmp_path / "ralph")
    env["CODEX_MEMORY_HOME"] = str(tmp_path / "empty-codex-memory")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    env["CODEX_SLOP_GUARD_ENABLED"] = "0"
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        shell=True,
        check=False,
    )


PLAIN_TEXT_ALLOWED_EVENTS = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}
COMMON_OUTPUT_EVENTS = {"SessionStart", "UserPromptSubmit", "Stop"}
POST_TOOL_OUTPUT_KEYS = {"decision", "reason", "systemMessage", "continue", "stopReason", "hookSpecificOutput"}
STOP_OUTPUT_KEYS = {"decision", "reason", "continue", "stopReason", "systemMessage", "suppressOutput"}


def assert_codex_hook_output_contract(event: str, command: str, result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, f"{event} {command}: {result.stderr or result.stdout}"
    output = result.stdout.strip()
    if not output:
        return
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        if event in PLAIN_TEXT_ALLOWED_EVENTS:
            return
        raise AssertionError(f"{event} {command} emitted invalid plain stdout: {output[:200]}") from exc

    decision = payload.get("decision")
    if decision is not None:
        assert decision == "block", f"{event} {command} emitted unsupported decision payload: {payload}"
        assert isinstance(payload.get("reason"), str) and payload["reason"].strip(), (
            f"{event} {command} emitted a block without a reason: {payload}"
        )

    if event == "PreToolUse":
        assert "continue" not in payload, f"{event} {command} emitted unsupported continue field: {payload}"
        assert "stopReason" not in payload, f"{event} {command} emitted unsupported stopReason field: {payload}"
        assert "suppressOutput" not in payload, f"{event} {command} emitted unsupported suppressOutput field: {payload}"
    elif event == "PostToolUse":
        extra = set(payload) - POST_TOOL_OUTPUT_KEYS
        assert not extra, f"{event} {command} emitted unsupported fields {sorted(extra)}: {payload}"
        if "continue" in payload:
            assert payload["continue"] is False, f"{event} {command} emitted unsupported continue value: {payload}"
        assert "suppressOutput" not in payload, f"{event} {command} emitted unsupported suppressOutput field: {payload}"
    elif event == "Stop":
        extra = set(payload) - STOP_OUTPUT_KEYS
        assert not extra, f"{event} {command} emitted unsupported fields {sorted(extra)}: {payload}"
    elif event not in COMMON_OUTPUT_EVENTS:
        assert "continue" not in payload, f"{event} {command} emitted unsupported continue field: {payload}"
        assert "stopReason" not in payload, f"{event} {command} emitted unsupported stopReason field: {payload}"

    hook_specific = payload.get("hookSpecificOutput")
    if isinstance(hook_specific, dict):
        hook_event_name = hook_specific.get("hookEventName")
        assert hook_event_name in {None, event}, f"{event} {command} emitted mismatched hook event: {payload}"


def test_local_and_global_hook_configs_stay_in_lockstep(tmp_path: Path) -> None:
    local = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    global_config = generated_global_config(tmp_path)

    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        assert hook_pairs(global_config, event) == hook_pairs(local, event)

    post_tool = [name for name, _timeout in hook_pairs(local, "PostToolUse")]
    assert post_tool.index("post_tool_extract_memory.py") < post_tool.index("post_tool_checkpoint.py")
    assert post_tool.index("post_tool_checkpoint.py") < post_tool.index("post_tool_cost_ledger.py")

    stop = [name for name, _timeout in hook_pairs(local, "Stop")]
    assert "implementation_notes_guard.py" in stop
    assert stop.index("stop_persist_memory.py") < stop.index("stop_memory_promotion_review.py")


def test_configured_stop_hooks_emit_only_codex_supported_output(tmp_path: Path) -> None:
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    session_id = f"stop-contract-{uuid.uuid4()}"
    payloads = [
        {
            "hook_event_name": "Stop",
            "session_id": session_id,
            "cwd": str(ROOT),
            "last_assistant_message": "Done.",
        },
        {
            "hook_event_name": "Stop",
            "session_id": f"{session_id}-report-only",
            "cwd": str(ROOT),
            "last_assistant_message": "Completed a multi-step local hook validation without a visible route marker.",
            "tool_call_count": 3,
        },
    ]

    for command in hook_commands(config, "Stop"):
        for payload in payloads:
            result = run_configured_hook(command, tmp_path, payload)
            assert_codex_hook_output_contract("Stop", command, result)


def test_configured_post_tool_hooks_emit_only_codex_supported_output(tmp_path: Path) -> None:
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    shaping_doc = tmp_path / "shaping.md"
    shaping_doc.write_text("---\nshaping: true\n---\n# Sensitive title should not leak\n", encoding="utf-8")
    large_file = tmp_path / "large.py"
    large_file.write_text("x\n" * 351, encoding="utf-8")
    payloads = [
        {
            "hook_event_name": "PostToolUse",
            "session_id": f"post-contract-{uuid.uuid4()}",
            "cwd": str(ROOT),
            "tool_name": "exec_command",
            "tool_use_id": "toolu_contract_simple",
            "tool_input": {"cmd": "git status --short --branch", "workdir": str(ROOT)},
            "tool_response": {"exit_code": 0, "stdout": "## main...origin/main\n"},
            "success": True,
        },
        {
            "hook_event_name": "PostToolUse",
            "session_id": f"post-contract-shaping-{uuid.uuid4()}",
            "cwd": str(tmp_path),
            "tool_name": "apply_patch",
            "tool_use_id": "toolu_contract_shaping",
            "tool_input": {"path": str(shaping_doc), "cwd": str(tmp_path)},
            "tool_response": {"status": "ok"},
            "success": True,
        },
        {
            "hook_event_name": "PostToolUse",
            "session_id": f"post-contract-file-line-{uuid.uuid4()}",
            "cwd": str(tmp_path),
            "tool_name": "apply_patch",
            "tool_use_id": "toolu_contract_file_line",
            "tool_input": {"path": str(large_file), "cwd": str(tmp_path)},
            "tool_response": {"status": "ok"},
            "success": True,
        },
    ]

    for command in hook_commands(config, "PostToolUse"):
        for payload in payloads:
            result = run_configured_hook(command, tmp_path, payload)
            assert_codex_hook_output_contract("PostToolUse", command, result)


def test_configured_prompt_and_pre_hooks_exit_cleanly_with_supported_output(tmp_path: Path) -> None:
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    payload_by_event = {
        "SessionStart": {
            "hook_event_name": "SessionStart",
            "session_id": f"session-contract-{uuid.uuid4()}",
            "cwd": str(ROOT),
            "source": "startup",
        },
        "UserPromptSubmit": {
            "hook_event_name": "UserPromptSubmit",
            "session_id": f"prompt-contract-{uuid.uuid4()}",
            "cwd": str(ROOT),
            "prompt": "revisa los hooks y valida el contrato esperado",
        },
        "PreToolUse": {
            "hook_event_name": "PreToolUse",
            "session_id": f"pre-contract-{uuid.uuid4()}",
            "cwd": str(ROOT),
            "tool_name": "exec_command",
            "tool_input": {"cmd": "git status --short --branch", "workdir": str(ROOT)},
        },
    }

    for event, payload in payload_by_event.items():
        for command in hook_commands(config, event):
            result = run_configured_hook(command, tmp_path, payload)
            assert_codex_hook_output_contract(event, command, result)
