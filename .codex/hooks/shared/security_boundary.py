"""Security-only PreToolUse boundaries.

This module deliberately contains no lifecycle, continuity, routing, memory, or
execution-authority logic. It is shared by the security-only dispatcher and
direct security tests so the preserved controls do not drift during migration.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from shared.active_context import active_context_from_payload
from shared.redaction import is_red, safe_preview

PATH_KEYS = ("path", "file_path", "filePath", "target_path", "targetPath", "filename")
PATCH_PATH_RE = re.compile(r"(?m)^\*\*\* (?:Add|Update|Delete) File: (?P<path>[^\r\n]+)$")
WRITE_TOOLS = {"apply_patch", "edit", "write"}


def tool_name(payload: dict[str, Any]) -> str:
    value = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")
    normalized = value.strip().lower().replace("-", "_").rsplit(".", 1)[-1]
    return normalized.rsplit("__", 1)[-1]


def raw_tool_name(payload: dict[str, Any]) -> str:
    return str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "").strip().lower()


def tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def deny(reason: object) -> dict[str, str]:
    text = safe_preview(reason, 240).strip()
    if not text or is_red(text):
        text = "Pre-tool security policy denied this action; inspect local sanitized diagnostics."
    return {"decision": "block", "reason": text}


def external_denial(payload: dict[str, Any]) -> dict[str, str] | None:
    """Keep RED material out of external/MCP tool inputs."""

    name = raw_tool_name(payload)
    if not (name.startswith("mcp__") or name.startswith("mcp.")):
        return None
    encoded = json.dumps(tool_input(payload), ensure_ascii=True, sort_keys=True, default=str)
    if is_red(encoded):
        return deny("Sensitive material must remain local and cannot be sent through an external tool.")
    return None


def raw_paths(payload: dict[str, Any], tool: str) -> list[str]:
    data = tool_input(payload)
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


def workspace_denial(payload: dict[str, Any], tool: str) -> dict[str, str] | None:
    """Keep native writes inside the active, non-symlink workspace."""

    if tool not in WRITE_TOOLS:
        return None
    context = active_context_from_payload(payload, resolve_git=False)
    workspace = (context.git_root or context.workspace_root).resolve()
    paths = raw_paths(payload, tool)
    if not paths:
        return deny("Write action has no bounded workspace path.")
    for raw in paths:
        candidate = Path(raw).expanduser()
        candidate = candidate if candidate.is_absolute() else workspace / candidate
        if _has_symlink_component(candidate):
            return deny("Write path crosses a symbolic link outside the trusted workspace boundary.")
        try:
            candidate.resolve(strict=False).relative_to(workspace)
        except (OSError, ValueError):
            return deny("Write path is outside the active workspace.")
    return None


__all__ = [
    "deny",
    "external_denial",
    "raw_paths",
    "tool_input",
    "tool_name",
    "workspace_denial",
]
