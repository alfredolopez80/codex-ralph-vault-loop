#!/usr/bin/env python3
"""Single-read PreToolUse dispatcher with deny-first composition."""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Callable

from pre_tool_guard import _guard_main
from sol_advisor_pretool_guard import _advisor_main
from subagent_routing_pretool_guard import _routing_main
from shared.active_context import active_context_from_payload
from shared.redaction import is_red, safe_preview
from shared.runtime_observability import record_event

MATCHER = r"Bash|exec_command|apply_patch|Edit|Write|Agent|spawn_agent|mcp__.*"
SPAWN_TOOLS = {"agent", "spawn_agent", "spawnagent"}
WRITE_TOOLS = {"apply_patch", "edit", "write"}
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
    return value.strip().lower().replace("-", "_").rsplit(".", 1)[-1]


def _tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


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
        patch = data.get("patch") or data.get("input") or payload.get("patch")
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
            tool_family=_tool_name(payload) or "unknown",
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
