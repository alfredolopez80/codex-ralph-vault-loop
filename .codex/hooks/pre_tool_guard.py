#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from shared.paths import REPO_ROOT, read_hook_input, write_json
from shared.redaction import is_red, sensitivity_report


DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+(/|~|\$HOME|\.)"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"),
    re.compile(r"\bgit\s+push\b.*\s--force\b"),
    re.compile(r"\bchmod\s+-R\s+777\b"),
]

SENSITIVE_COMMAND_PATTERNS = [
    re.compile(
        r"(?i)\b(cat|less|more|head|tail|sed|awk|pbcopy|open|curl|wget|scp|rsync)\b"
        r".*(\.env|id_rsa|id_ed25519|\.pem|\.key|wallet|credential|secret|token)"
    ),
    re.compile(r"(?i)\b(echo|printf|curl|wget|npx|node|python3?)\b.*(api[_-]?key|secret|token|password|credential)"),
]

AUTOMATION_MUTATION_MODES = {"create", "update"}
AUTOMATION_REVIEW_MODES = {"suggested_create", "suggested_update"}
DOTFILE_PERSISTENCE_PATTERNS = [
    re.compile(r"(?i)(^|[\s/])\.(bashrc|bash_profile|profile|zshenv|zprofile|zshrc)\b"),
    re.compile(r"(?i)\bLaunchAgents\b|\bcrontab\b|\bshell\s+startup\b|\blogin\s+shell\b"),
]

HOME = Path.home().resolve()
SHELL_COMPLEXITY_RE = re.compile(r"&&|\|\||;|\||`|\$\(")

SFW_PROTECTED_COMMANDS = {
    "bun": {"add", "install", "update", "x"},
    "bundle": {"add", "install", "update"},
    "cargo": {"add", "fetch", "install", "update"},
    "composer": {"install", "require", "update"},
    "gem": {"install", "update"},
    "go": {"get", "install"},
    "npm": {"add", "ci", "exec", "install", "i", "update", "x"},
    "npx": None,
    "pip": {"install"},
    "pip3": {"install"},
    "pnpm": {"add", "dlx", "exec", "i", "import", "install", "update", "up"},
    "uv": {"add", "pip", "run", "sync", "tool"},
    "uvx": None,
    "yarn": {"add", "dlx", "exec", "install", "up", "upgrade"},
}
PYTHON_BINARIES = {"python", "python3", "python3.10", "python3.11", "python3.12", "python3.13", "python3.14"}
SFW_BLOCK_REASON = "Package-manager network commands must run through sfw."
SFW_GUIDANCE = "Re-run the package-manager segment with sfw as the prefix."
ENV_OPTIONS_WITH_VALUE = {"-u", "--unset", "-C", "--chdir", "--argv0"}
ENV_SPLIT_STRING_OPTIONS = {"-S", "--split-string"}


def executable_name(token: str) -> str:
    return Path(token).name.lower()


def is_assignment_prefix(token: str) -> bool:
    return "=" in token and not token.startswith("-") and bool(token.split("=", 1)[0])


def strip_env_invocation(tokens: list[str]) -> list[str]:
    index = 1
    while index < len(tokens):
        shell_arg = tokens[index]
        if shell_arg == "--":
            return tokens[index + 1 :]
        if shell_arg in ENV_SPLIT_STRING_OPTIONS:
            if index + 1 >= len(tokens):
                return []
            try:
                split_tokens = shlex.split(tokens[index + 1])
            except ValueError:
                return []
            return strip_environment_prefix(split_tokens + tokens[index + 2 :])
        if any(shell_arg.startswith(option + "=") for option in ENV_SPLIT_STRING_OPTIONS if option.startswith("--")):
            try:
                split_tokens = shlex.split(shell_arg.split("=", 1)[1])
            except ValueError:
                return []
            return strip_environment_prefix(split_tokens + tokens[index + 1 :])
        if shell_arg in ENV_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if any(shell_arg.startswith(option + "=") for option in ENV_OPTIONS_WITH_VALUE if option.startswith("--")):
            index += 1
            continue
        if shell_arg.startswith("-"):
            index += 1
            continue
        if is_assignment_prefix(shell_arg):
            index += 1
            continue
        return tokens[index:]
    return []


def strip_environment_prefix(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens):
        shell_arg = tokens[index]
        if shell_arg == "env":
            return strip_env_invocation(tokens[index:])
        if is_assignment_prefix(shell_arg):
            index += 1
            continue
        break
    return tokens[index:]


def has_environment_prefix(tokens: list[str]) -> bool:
    if not tokens:
        return False
    if tokens[0] == "env":
        return True
    return is_assignment_prefix(tokens[0])


def command_tokens(command: str) -> list[str]:
    try:
        return strip_environment_prefix(shlex.split(command))
    except ValueError:
        return []


def python_invokes_pip(tokens: list[str]) -> bool:
    if len(tokens) < 4:
        return False
    if executable_name(tokens[0]) not in PYTHON_BINARIES:
        return False
    if tokens[1] != "-m" or tokens[2] != "pip":
        return False
    return tokens[3] == "install"


def tokens_require_sfw(tokens: list[str]) -> bool:
    if not tokens:
        return False
    if executable_name(tokens[0]) == "sfw":
        return False
    if python_invokes_pip(tokens):
        return True

    tool = executable_name(tokens[0])
    protected_subcommands = SFW_PROTECTED_COMMANDS.get(tool)
    if protected_subcommands is None:
        return tool in SFW_PROTECTED_COMMANDS
    if protected_subcommands is not None and len(tokens) > 1:
        return tokens[1] in protected_subcommands
    return False


def command_requires_sfw(command: str) -> bool:
    return tokens_require_sfw(command_tokens(command))


def sfw_protection_payload(command: str) -> dict[str, str] | None:
    if SHELL_COMPLEXITY_RE.search(command):
        tokens = command_tokens(command)
        if tokens_require_sfw(tokens):
            return {"reason": SFW_GUIDANCE}
        return None

    try:
        raw_tokens = shlex.split(command)
    except ValueError:
        return None
    tokens = strip_environment_prefix(raw_tokens)
    if not tokens_require_sfw(tokens):
        return None
    if has_environment_prefix(raw_tokens):
        return {"reason": SFW_GUIDANCE}
    return {"reason": SFW_BLOCK_REASON, "suggested_command": shlex.join(["sfw", *tokens])}


def tool_input_from_payload(payload: dict[str, Any]) -> Any:
    return payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}


def tool_name_from_payload(payload: dict[str, Any]) -> str:
    return str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")


def command_from_payload(payload: dict[str, Any]) -> str:
    tool_input = tool_input_from_payload(payload)
    if isinstance(tool_input, dict):
        return str(tool_input.get("command") or tool_input.get("cmd") or "")
    return str(tool_input)


def is_automation_payload(payload: dict[str, Any], tool_input: Any) -> bool:
    tool_name = tool_name_from_payload(payload)
    if "automation_update" in tool_name:
        return True
    return isinstance(tool_input, dict) and (
        "kind" in tool_input
        or "rrule" in tool_input
        or "executionEnvironment" in tool_input
        or "cwds" in tool_input
    )


def normalize_string(value: Any) -> str:
    return str(value or "").strip().lower()


def configured_cwds(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def resolve_user_path(value: str) -> Path | None:
    try:
        expanded = os.path.expanduser(os.path.expandvars(value))
        return Path(expanded).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def cwd_targets_home_or_external_workspace(value: str) -> bool:
    path = resolve_user_path(value)
    if path is None:
        return True
    if path == HOME:
        return True
    if is_relative_to(path, REPO_ROOT):
        return False
    return is_relative_to(path, HOME)


def prompt_targets_local_persistence(prompt: str) -> bool:
    return any(pattern.search(prompt) for pattern in DOTFILE_PERSISTENCE_PATTERNS)


def blocked_automation_reason(payload: dict[str, Any]) -> str | None:
    tool_input = tool_input_from_payload(payload)
    if not is_automation_payload(payload, tool_input):
        return None
    if not isinstance(tool_input, dict):
        return None

    mode = normalize_string(tool_input.get("mode"))
    if mode in AUTOMATION_REVIEW_MODES:
        return None
    if mode not in AUTOMATION_MUTATION_MODES:
        return None

    prompt = str(tool_input.get("prompt") or "")
    if prompt_targets_local_persistence(prompt):
        return "Blocked direct automation mutation that targets shell persistence files."

    execution_environment = normalize_string(tool_input.get("executionEnvironment"))
    if execution_environment == "local":
        return "Blocked direct local automation mutation; use a reviewable suggestion flow."

    kind = normalize_string(tool_input.get("kind"))
    if kind == "cron":
        cwds = configured_cwds(tool_input.get("cwds"))
        if not cwds:
            return "Blocked direct cron automation mutation without an explicit safe workspace."
        if any(cwd_targets_home_or_external_workspace(cwd) for cwd in cwds):
            return "Blocked direct cron automation mutation targeting a home or external workspace path."

    return None


def main() -> int:
    payload = read_hook_input()
    automation_reason = blocked_automation_reason(payload)
    if automation_reason:
        write_json({"decision": "block", "reason": automation_reason})
        return 0

    command = command_from_payload(payload)
    if not command:
        return 0

    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            write_json({"decision": "block", "reason": "Blocked obvious destructive command by pre_tool_guard."})
            return 0
    for pattern in SENSITIVE_COMMAND_PATTERNS:
        if pattern.search(command):
            write_json({"decision": "block", "reason": "Blocked command that could expose RED-sensitive material."})
            return 0
    sfw_payload = sfw_protection_payload(command)
    if sfw_payload:
        write_json({"decision": "block", **sfw_payload})
        return 0
    if is_red(command):
        report = sensitivity_report(command)
        finding_labels = [item["label"] for item in report.get("findings", []) if isinstance(item, dict)]
        write_json(
            {
                "decision": "block",
                "reason": "Blocked command containing RED-sensitive material.",
                "findings": finding_labels,
            }
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
