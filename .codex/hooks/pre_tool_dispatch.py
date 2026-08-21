#!/usr/bin/env python3
"""Single-read PreToolUse dispatcher with deny-first composition."""
from __future__ import annotations

import io
import json
import os
import re
import shlex
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Callable

from pre_tool_guard import _guard_main
from sol_advisor_pretool_guard import _advisor_main
from subagent_routing_pretool_guard import _routing_main
from shared.active_context import active_context_from_payload
from shared.convergence_authority import AuthorityError, load_authoritative_state
from shared.convergent_hooks import is_read_only_command
from shared.execution_policy import configured_activation_mode
from shared.redaction import is_red, safe_preview
from shared.runtime_observability import record_event

MATCHER = r"Bash|exec_command|apply_patch|Edit|Write|Agent|spawn_agent|mcp__.*"
SPAWN_TOOLS = {"agent", "spawn_agent", "spawnagent"}
WRITE_TOOLS = {"apply_patch", "edit", "write"}
COMMAND_TOOLS = {"bash", "exec_command", "run_command", "shell", "sh", "terminal", "zsh"}
VALIDATION_TASKS = {"test", "build", "lint", "typecheck"}
VALIDATION_SCRIPTS = {
    ".codex/tests/run-hook-tests.sh",
    "scripts/validate-ralph-memory-flow.sh",
}
PYTHON_VALIDATION_SCRIPTS = {"scripts/gates/run-gates.py"}
ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=[^\x00\r\n]*$")
PATH_KEYS = ("path", "file_path", "filePath", "target_path", "targetPath", "filename")
PATCH_PATH_RE = re.compile(r"(?m)^\*\*\* (?:Add|Update|Delete) File: (?P<path>[^\r\n]+)$")
MAX_COMPONENT_OUTPUT_BYTES = 64 * 1024


class _BoundedOutput(io.StringIO):
    """Keep compatibility component diagnostics from growing without bound."""

    def write(self, value: str) -> int:
        remaining = MAX_COMPONENT_OUTPUT_BYTES - self.tell()
        if remaining > 0:
            super().write(value[:remaining])
        return len(value)


def _parse_input() -> dict[str, Any] | None:
    try:
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        value = stream.read(4 * 1024 * 1024 + 1)
        raw = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        if len(raw.encode("utf-8")) > 4 * 1024 * 1024:
            sys.stderr.write("pre_tool_dispatch input exceeded its bounded limit; action unknown and allowed.\n")
            return None
        value = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError):
        sys.stderr.write("pre_tool_dispatch invalid JSON; action unknown and allowed.\n")
        return None
    if not isinstance(value, dict):
        sys.stderr.write("pre_tool_dispatch payload is not an object; action unknown and allowed.\n")
        return None
    return value


def _tool_name(payload: dict[str, Any]) -> str:
    value = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")
    normalized = value.strip().lower().replace("-", "_").rsplit(".", 1)[-1]
    return normalized.rsplit("__", 1)[-1]


def _tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _command(payload: dict[str, Any]) -> str:
    data = _tool_input(payload)
    for value in (payload.get("command"), payload.get("cmd"), data.get("command"), data.get("cmd")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_validation_command(command: str) -> bool:
    """Recognize one closed-world validation command, never a shell chain."""

    if not command or len(command.encode("utf-8", errors="replace")) > 4_096:
        return False
    if any(marker in command for marker in ("\n", "\r", ";", "|", "&", ">", "<", "`", "$")):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    while tokens and ENV_ASSIGNMENT_RE.fullmatch(tokens[0]):
        tokens.pop(0)
    if not tokens or "/" in tokens[0] or "\\" in tokens[0]:
        return False
    executable = tokens[0].lower()
    arguments = tokens[1:]
    if executable in {"python", "python3"}:
        return (len(arguments) >= 2 and arguments[:2] == ["-m", "pytest"]) or (
            bool(arguments) and arguments[0] in PYTHON_VALIDATION_SCRIPTS
        )
    if executable == "pytest":
        return True
    if executable in {"npm", "pnpm"}:
        if arguments[:1] == ["run"]:
            arguments = arguments[1:]
        return bool(arguments) and arguments[0].lower() in VALIDATION_TASKS
    if executable == "make":
        return len(arguments) == 1 and arguments[0].lower() in {"test", "build"}
    if executable == "mypy":
        return True
    if executable == "ruff":
        mutating = any(argument in {"--fix", "--fix-only"} or argument.startswith("--fix=") for argument in arguments)
        return not mutating and (
            arguments[:1] == ["check"] or (arguments[:1] == ["format"] and "--check" in arguments)
        )
    if executable == "tsc":
        return "--noEmit" in arguments
    return executable == "bash" and len(arguments) == 1 and arguments[0] in VALIDATION_SCRIPTS


def _external_denial(payload: dict[str, Any]) -> dict[str, str] | None:
    value = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "").lower()
    if not (value.startswith("mcp__") or value.startswith("mcp.")):
        return None
    encoded = json.dumps(_tool_input(payload), ensure_ascii=True, sort_keys=True, default=str)
    if is_red(encoded):
        return _deny("Sensitive material must remain local and cannot be sent through an external tool.")
    return None


def _raw_paths(payload: dict[str, Any], tool: str) -> list[str]:
    data = _tool_input(payload)
    values = [str(data[key]).strip() for key in PATH_KEYS if isinstance(data.get(key), str) and str(data[key]).strip()]
    if tool == "apply_patch":
        patch = data.get("patch") or data.get("input") or data.get("command") or payload.get("patch")
        if isinstance(patch, str):
            values.extend(match.group("path").strip() for match in PATCH_PATH_RE.finditer(patch))
    return list(dict.fromkeys(values))


def _has_symlink_component(path: Path) -> bool:
    candidate = Path(os.path.abspath(os.fspath(path)))
    for item in (candidate, *candidate.parents):
        if item.exists() and item.is_symlink():
            return True
        if item == item.parent:
            break
    return False


def _workspace_denial(payload: dict[str, Any], tool: str) -> dict[str, str] | None:
    if tool not in WRITE_TOOLS:
        return None
    context = active_context_from_payload(payload, resolve_git=False)
    workspace = (context.git_root or context.workspace_root).resolve()
    paths = _raw_paths(payload, tool)
    if not paths:
        return _deny("Write action has no bounded workspace path.")
    for raw in paths:
        candidate = Path(raw).expanduser()
        candidate = candidate if candidate.is_absolute() else workspace / candidate
        if _has_symlink_component(candidate):
            return _deny("Write path crosses a symbolic link outside the trusted workspace boundary.")
        try:
            candidate.resolve(strict=False).relative_to(workspace)
        except (OSError, ValueError):
            return _deny("Write path is outside the active workspace.")
    return None


def _component(
    component: Callable[[dict[str, Any]], int], payload: dict[str, Any]
) -> tuple[dict[str, Any] | None, bool]:
    output = _BoundedOutput()
    try:
        with redirect_stdout(output):
            component(payload)
        rendered = output.getvalue().strip()
        if not rendered:
            return None, False
        value = json.loads(rendered)
        return (value, False) if isinstance(value, dict) else (None, True)
    except Exception:
        return None, True


def _deny(reason: object) -> dict[str, str]:
    text = safe_preview(reason, 240).strip()
    if not text or is_red(text):
        text = "Pre-tool policy denied this action; inspect local sanitized diagnostics."
    return {"decision": "block", "reason": text}


def _convergent_phase_gate(payload: dict[str, Any], tool: str) -> dict[str, str] | None:
    """Apply the narrow v4 write-phase gate after the existing safety owners.

    Reads remain on the established path. Explicit write tools and shell
    commands that are not proven read-only are gated so an enforce mutation
    cannot bypass lifecycle authority by travelling through ``exec_command``.
    """

    if tool not in WRITE_TOOLS and tool not in COMMAND_TOOLS:
        return None
    command = _command(payload) if tool in COMMAND_TOOLS else ""
    if command and is_read_only_command(command):
        return None
    context = active_context_from_payload(payload, resolve_git=False)
    try:
        mode = configured_activation_mode(workspace_root=context.workspace_root)
    except Exception:
        return _deny("Convergent activation configuration is invalid.")
    if mode != "enforce":
        return None
    try:
        _authority, state = load_authoritative_state(payload)
    except AuthorityError:
        return _deny("Convergent authority and manual activation approval are required for a write.")
    allowed_phases = {"implement", "mitigate"}
    if tool in COMMAND_TOOLS and _is_validation_command(command):
        allowed_phases |= {"verify", "final_audit"}
    if state.get("phase") not in allowed_phases:
        return _deny("The active convergent phase does not accept this command or implementation write.")
    return None


def dispatch(payload: dict[str, Any]) -> tuple[dict[str, str] | None, list[str]]:
    tool = _tool_name(payload)
    if not tool:
        return None, ["invalid_action"]
    executed = ["safety"]
    safety, failed = _component(_guard_main, payload)
    if failed:
        return _deny("Safety validation failed for the identified action."), executed
    if safety and safety.get("decision") == "block":
        return _deny(safety.get("reason")), executed
    executed.append("egress")
    egress = _external_denial(payload)
    if egress:
        return egress, executed
    executed.append("workspace_integrity")
    workspace = _workspace_denial(payload, tool)
    if workspace:
        return workspace, executed
    executed.append("convergent_phase_gate")
    phase_gate = _convergent_phase_gate(payload, tool)
    if phase_gate:
        return phase_gate, executed
    if tool in SPAWN_TOOLS:
        executed.append("subagent_routing")
        routing, failed = _component(_routing_main, payload)
        if failed:
            return _deny("Subagent routing validation failed."), executed
        if routing and routing.get("decision") == "block":
            return _deny(routing.get("reason")), executed
        executed.append("sol_advisor_eligibility")
        advisor, failed = _component(_advisor_main, payload)
        if failed:
            return _deny("Advisor eligibility validation failed."), executed
        if advisor and advisor.get("decision") == "block":
            return _deny(advisor.get("reason")), executed
    return None, executed


def main() -> int:
    started = time.perf_counter_ns()
    payload = _parse_input()
    if payload is None:
        return 0
    response: dict[str, str] | None = None
    executed: list[str] = []
    try:
        response, executed = dispatch(payload)
    except Exception:
        response = _deny("Pre-tool validation failed for the identified action.") if _tool_name(payload) else None
    if response:
        sys.stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")
    tool = _tool_name(payload)
    # Successful local reads are already protected by the deny-first checks
    # above. Avoid turning routine inspection into a durable telemetry write.
    if response is None and tool in COMMAND_TOOLS and is_read_only_command(_command(payload)):
        return 0
    try:
        context = active_context_from_payload(payload, resolve_git=False)
        record_event(
            context,
            payload,
            event="pre_tool",
            dispatcher="pre_tool_dispatch",
            duration_ns=time.perf_counter_ns() - started,
            process_count=1,
            child_process_count=0,
            tool_family=tool or "unknown",
            components_considered=["safety", "egress", "workspace_integrity", "subagent_routing", "sol_advisor_eligibility"],
            components_executed=executed,
            output_bytes=len(json.dumps(response).encode("utf-8")) if response else 0,
            block_reason_code=["pre_tool_denied"] if response else [],
            success=response is None,
            scenario=payload.get("scenario"),
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
