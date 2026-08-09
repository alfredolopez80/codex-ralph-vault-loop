"""Read hook configuration and evaluate official matcher-shaped groups."""
from __future__ import annotations

import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


MATCHER_VALUE_KEYS = {
    "SessionStart": ("source",),
    "PreToolUse": ("tool_name", "toolName", "tool"),
    "PostToolUse": ("tool_name", "toolName", "tool"),
    "SubagentStart": ("agent_type", "agentType"),
    "SubagentStop": ("agent_type", "agentType"),
}


@dataclass(frozen=True)
class HandlerSpec:
    event: str
    matcher: str
    role: str
    command: tuple[str, ...]
    timeout: float


def load_hook_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load hook configuration: {path}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("hooks"), dict):
        raise ValueError(f"invalid hook configuration: {path}")
    return value


def configured_handler_counts(config: Mapping[str, object]) -> dict[str, int]:
    hooks = config.get("hooks")
    if not isinstance(hooks, Mapping):
        raise ValueError("hook configuration has no hooks object")
    counts: dict[str, int] = {}
    for event, raw_groups in hooks.items():
        if not isinstance(event, str) or not isinstance(raw_groups, list):
            raise ValueError("hook event groups must be lists")
        total = 0
        for group in raw_groups:
            if not isinstance(group, Mapping) or not isinstance(group.get("hooks"), list):
                raise ValueError(f"invalid hook group for {event}")
            total += len(group["hooks"])
        counts[event] = total
    return dict(sorted(counts.items()))


def matcher_value(event: str, payload: Mapping[str, object]) -> str:
    for key in MATCHER_VALUE_KEYS.get(event, ()):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def group_matches(event: str, group: Mapping[str, object], payload: Mapping[str, object]) -> bool:
    matcher = group.get("matcher")
    if matcher is None:
        return True
    if not isinstance(matcher, str) or not matcher:
        raise ValueError(f"invalid matcher for {event}")
    try:
        pattern = re.compile(matcher)
    except re.error as exc:
        raise ValueError(f"invalid matcher for {event}: {matcher!r}") from exc
    return pattern.fullmatch(matcher_value(event, payload)) is not None


def matched_handlers(config: Mapping[str, object], event: str, payload: Mapping[str, object]) -> int:
    hooks = config.get("hooks")
    if not isinstance(hooks, Mapping):
        raise ValueError("hook configuration has no hooks object")
    groups = hooks.get(event, [])
    if not isinstance(groups, list):
        raise ValueError(f"hook groups for {event} must be a list")
    total = 0
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("hooks"), list):
            raise ValueError(f"invalid hook group for {event}")
        if group_matches(event, group, payload):
            total += len(group["hooks"])
    return total


def _resolved_command(command: str, root: Path) -> tuple[str, ...]:
    substitutions = (
        '"$(git rev-parse --show-toplevel)',
        "'$(git rev-parse --show-toplevel)",
        "$(git rev-parse --show-toplevel)",
    )
    rendered = command
    for marker in substitutions:
        quote = marker[0] if marker[0] in {'"', "'"} else ""
        rendered = rendered.replace(marker, quote + str(root))
    try:
        argv = shlex.split(rendered)
    except ValueError as exc:
        raise ValueError("hook command is not parseable") from exc
    if not argv:
        raise ValueError("hook command is empty")
    if argv[0] in {"python", "python3"}:
        argv[0] = sys.executable
    for index, argument in enumerate(argv[1:], start=1):
        candidate = Path(argument)
        if argument.startswith(".codex/"):
            candidate = root / candidate
        if candidate.suffix in {".py", ".sh"}:
            resolved = candidate.resolve(strict=False)
            try:
                resolved.relative_to((root / ".codex" / "hooks").resolve())
            except ValueError as exc:
                raise ValueError("hook command escapes the configured hook root") from exc
            argv[index] = str(resolved)
    return tuple(argv)


def handler_specs(
    config: Mapping[str, object], event: str, payload: Mapping[str, object], *, root: Path
) -> list[HandlerSpec]:
    hooks = config.get("hooks")
    if not isinstance(hooks, Mapping):
        raise ValueError("hook configuration has no hooks object")
    groups = hooks.get(event, [])
    if not isinstance(groups, list):
        raise ValueError(f"hook groups for {event} must be a list")
    specs: list[HandlerSpec] = []
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("hooks"), list):
            raise ValueError(f"invalid hook group for {event}")
        if not group_matches(event, group, payload):
            continue
        matcher = str(group.get("matcher") or "")
        for raw_handler in group["hooks"]:
            if not isinstance(raw_handler, Mapping) or not isinstance(raw_handler.get("command"), str):
                raise ValueError(f"invalid command handler for {event}")
            command = _resolved_command(str(raw_handler["command"]), root)
            script = next((Path(arg) for arg in command if Path(arg).suffix in {".py", ".sh"}), None)
            role = script.stem.replace("-", "_") if script is not None else "command"
            try:
                timeout = float(raw_handler.get("timeout", 10))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid timeout for {event}/{role}") from exc
            specs.append(HandlerSpec(event, matcher, role, command, timeout))
    return specs


__all__ = [
    "HandlerSpec",
    "configured_handler_counts",
    "group_matches",
    "handler_specs",
    "load_hook_config",
    "matched_handlers",
    "matcher_value",
]
