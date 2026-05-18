#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from shared.checkpoint_io import update_checkpoint
from shared.paths import append_jsonl, ensure_runtime, now_iso, read_hook_input
from shared.redaction import is_red, safe_preview


TEST_MARKERS = ("test", "pytest", "pnpm test", "npm test", "make test")
BUILD_MARKERS = ("build", "typecheck", "lint")
GIT_MARKERS = ("git ", "git-")


def main() -> int:
    payload = read_hook_input()
    update = checkpoint_update_from_payload(payload)
    if not update:
        return 0
    result = update_checkpoint(update)
    root = ensure_runtime()
    append_jsonl(
        root / "checkpoints" / "post-tool-events.jsonl",
        {
            "created_at": now_iso(),
            "event": "post_tool_checkpoint",
            "status": result.get("status", "unknown"),
            "source": update.get("source", "PostToolUse"),
        },
    )
    return 0


def checkpoint_update_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    command = command_from_payload(payload)
    active_files = active_files_from_payload(payload)
    success = success_from_payload(payload)
    if not command and not active_files and success is not False:
        return None
    if unsafe_payload(payload, command):
        return None

    update: dict[str, Any] = {
        "source": "PostToolUse",
        "current_phase": "PostToolUse",
    }
    if active_files:
        update["active_files"] = active_files
    if command:
        update["commands_run"] = [{"command": command, "result": result_label(success), "summary": summary_for(command, success)}]
        if is_validation_command(command):
            update["validation_status"] = "pass" if success is True else "fail" if success is False else "partial"
            update["last_verified_state"] = summary_for(command, success)
    if success is False:
        update["blockers"] = [f"Command failed: {command or tool_name(payload)}"]
    if not update.get("last_verified_state") and active_files:
        update["last_verified_state"] = "Tracked file changes for current task."
    return update


def command_from_payload(payload: dict[str, Any]) -> str:
    candidates = [payload.get("command"), payload.get("cmd")]
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        candidates.extend([tool_input.get("command"), tool_input.get("cmd")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return safe_preview(candidate, 180)
    return ""


def active_files_from_payload(payload: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("path", "file", "files", "paths"):
        if payload.get(key):
            values.append(payload[key])
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("path", "file", "files", "paths"):
            if tool_input.get(key):
                values.append(tool_input[key])
    files: list[str] = []
    for value in values:
        items = value if isinstance(value, list) else [value]
        for item in items:
            text = safe_preview(str(item), 220)
            if text and text not in files:
                files.append(text)
    return files[:12]


def success_from_payload(payload: dict[str, Any]) -> bool | None:
    if isinstance(payload.get("success"), bool):
        return payload["success"]
    for key in ("exit_code", "returncode", "return_code"):
        value = payload.get(key)
        if isinstance(value, int):
            return value == 0
    return None


def unsafe_payload(payload: dict[str, Any], command: str) -> bool:
    material = " ".join(
        str(value)
        for value in (
            command,
            payload.get("output", ""),
            payload.get("output_preview", ""),
            payload.get("outputPreview", ""),
            payload.get("result", ""),
        )
    )
    return is_red(material)


def is_validation_command(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in TEST_MARKERS + BUILD_MARKERS)


def summary_for(command: str, success: bool | None) -> str:
    prefix = "Command passed" if success is True else "Command failed" if success is False else "Command result unknown"
    return f"{prefix}: {command}"


def result_label(success: bool | None) -> str:
    if success is True:
        return "pass"
    if success is False:
        return "fail"
    return "unknown"


def tool_name(payload: dict[str, Any]) -> str:
    return safe_preview(str(payload.get("tool_name") or payload.get("tool") or "tool"), 80)


if __name__ == "__main__":
    raise SystemExit(main())
