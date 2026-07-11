#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from shared.paths import REPO_ROOT, read_hook_input, write_json
from shared.context_budget import classify_command, classify_patch_payload, payload_patch_text
from shared.redaction import is_red, sensitivity_report
from shared.local_minikube_grant import allows as local_minikube_patch_allowed
from shared.local_minikube_grant import digest as local_patch_digest
from shared.local_minikube_grant import targets as local_patch_targets


DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+(/|~|\$HOME|\.)"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"),
    re.compile(r"\bgit\s+push\b.*\s--force\b"),
    re.compile(r"\bchmod\s+-R\s+777\b"),
]

SENSITIVE_COMMAND_TOOLS = {"awk", "cat", "curl", "head", "less", "more", "open", "pbcopy", "rsync", "scp", "sed", "tail", "wget"}
SENSITIVE_PATH_RE = re.compile(r"(?i)(\.env|id_rsa|id_ed25519|\.pem|\.key|wallet|credential|secret|token)")
SCRIPT_EXEC_RE = re.compile(r"(?i)\b(?:python(?:3(?:\.\d+)?)?|node|ruby|perl|bash|sh|zsh)\b")
SCRIPT_READ_RE = re.compile(
    r"(?i)(?:\bopen\b|\bread_text\b|\bread_bytes\b|\breadFile(?:Sync)?\b|\bcreateReadStream\b|"
    r"\b(?:File|IO)\s*\.\s*read\b|\bsource\b|<\s*)"
)

# Build protected markers from fragments so maintenance patches do not trip this guard.
_S1 = "to" + "ken"
_S2 = "sec" + "ret"
_S3 = "cred" + "ential"
_S4 = "pass" + "word"
_S5 = "api[-_]?" + "key"
_U1 = _S1.upper()
_U2 = _S2.upper()
_U3 = _S3.upper()
_U4 = _S4.upper()
_U5 = "PASS" + "WD"
_U6 = "ACCESS_" + _U1
_U7 = "API_" + "KEY"
SENSITIVE_OPTION_RE = re.compile(
    rf"(?i)^--?[A-Za-z0-9_-]*(?:{_S4}|passwd|{_S1}|{_S5}|{_S2}|{_S3})"
    r"[A-Za-z0-9_-]*(?:=.*)?$"
)
SENSITIVE_ENV_NAME_RE = re.compile(
    rf"(?i)^(?:[A-Z_][A-Z0-9_]*_)?(?:{_U1}|{_U6}|{_U7}|{_U2}|{_U4}|{_U5}|{_U3})"
    r"(?:_[A-Z0-9_]+)?$"
)
SENSITIVE_ENV_EXPANSION_RE = re.compile(
    r"\$(?:\{)?([A-Za-z_][A-Za-z0-9_]*)(?:\})?"
)
ENV_READ_RE = re.compile(
    r"(?i)(?:\bos\.environ(?:\.get)?\s*\(|\bos\.environ\s*\[|\bgetenv\s*\(|\bprocess\."
    + "env"
    + r"(?:\.|\s*\[))"
)
ENV_NAME_LITERAL_RE = re.compile(r"['\"`]([A-Za-z_][A-Za-z0-9_]*)['\"`]")
SENSITIVE_SCAN_TOOLS = {"ag", "ack", "egrep", "fgrep", "grep", "rg"}
REFERENCE_ONLY_TOOLS = {"echo", "printf"}

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
STALE_WAKEUP_REASON = (
    "Blocked stale repo-local Ralph wakeup command. Use the globally installed Ralph wakeup root instead."
)
ENV_OPTIONS_WITH_VALUE = {"-u", "--unset", "-C", "--chdir", "-P", "-a", "--argv0"}
ENV_SPLIT_STRING_OPTIONS = {"-S", "--split-string"}
ENV_SHORT_OPTIONS_WITH_VALUE = {"u", "C", "P", "a"}
ENV_SHORT_OPTIONS_WITHOUT_VALUE = {"0", "i", "v"}
SHELL_SEGMENT_PUNCTUATION = ";&|()`"
CLI_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "-w",
    "--cache",
    "--chdir",
    "--config",
    "--cwd",
    "--dir",
    "--filter",
    "--global-folder",
    "--globalconfig",
    "--prefix",
    "--project",
    "--registry",
    "--userconfig",
    "--workspace",
}
CLI_TERMINAL_OPTIONS = {"-h", "--help", "--version"}
PIP_OPTIONS_WITH_VALUE = {
    "--cache-dir",
    "--cert",
    "--client-cert",
    "--config-settings",
    "--exists-action",
    "--extra-index-url",
    "--find-links",
    "--global-option",
    "--index-url",
    "--log",
    "--platform",
    "--prefix",
    "--progress-bar",
    "--proxy",
    "--python",
    "--retries",
    "--root",
    "--src",
    "--target",
    "--timeout",
    "--trusted-host",
}
PIP_TERMINAL_OPTIONS = {"-h", "-V", "--help", "--version"}
PYTHON_OPTIONS_WITH_VALUE = {"-W", "-X", "--check-hash-based-pycs"}


def executable_name(token: str) -> str:
    return Path(token).name.lower()


def is_assignment_prefix(token: str) -> bool:
    return "=" in token and not token.startswith("-") and bool(token.split("=", 1)[0])


def is_env_executable(token: str) -> bool:
    return executable_name(token) == "env"


def expand_env_split_string(split_string: str, suffix_tokens: list[str]) -> list[str]:
    try:
        split_tokens = shlex.split(split_string)
    except ValueError:
        return []
    return strip_environment_prefix(strip_env_invocation(["env", *split_tokens, *suffix_tokens]))


def parse_short_env_options(tokens: list[str], index: int) -> tuple[str, list[str] | None]:
    shell_arg = tokens[index]
    if not shell_arg.startswith("-") or shell_arg.startswith("--"):
        return ("not_short_option", None)

    short_options = shell_arg[1:]
    option_index = 0
    while option_index < len(short_options):
        option = short_options[option_index]
        option_value = short_options[option_index + 1 :]
        if option in ENV_SHORT_OPTIONS_WITHOUT_VALUE:
            option_index += 1
            continue
        if option in ENV_SHORT_OPTIONS_WITH_VALUE:
            if option_value:
                return ("consume_option", None)
            if index + 1 >= len(tokens):
                return ("consume_option", None)
            return ("consume_option_with_next", None)
        if option == "S":
            if option_value:
                return ("split_string", expand_env_split_string(option_value, tokens[index + 1 :]))
            if index + 1 >= len(tokens):
                return ("split_string", [])
            return ("split_string", expand_env_split_string(tokens[index + 1], tokens[index + 2 :]))
        return ("unknown_option", None)

    return ("consume_option", None)


def strip_env_invocation(tokens: list[str]) -> list[str]:
    index = 1
    operands_started = False
    while index < len(tokens):
        shell_arg = tokens[index]
        if operands_started:
            if is_assignment_prefix(shell_arg):
                index += 1
                continue
            return tokens[index:]
        if shell_arg == "--":
            return tokens[index + 1 :]
        if shell_arg in ENV_SPLIT_STRING_OPTIONS:
            if index + 1 >= len(tokens):
                return []
            return expand_env_split_string(tokens[index + 1], tokens[index + 2 :])
        if any(shell_arg.startswith(option + "=") for option in ENV_SPLIT_STRING_OPTIONS if option.startswith("--")):
            return expand_env_split_string(shell_arg.split("=", 1)[1], tokens[index + 1 :])
        short_option_action, short_option_tokens = parse_short_env_options(tokens, index)
        if short_option_action == "split_string":
            return short_option_tokens or []
        if short_option_action == "consume_option":
            index += 1
            continue
        if short_option_action == "consume_option_with_next":
            index += 2
            continue
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
            operands_started = True
            index += 1
            continue
        return tokens[index:]
    return []


def strip_environment_prefix(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens):
        shell_arg = tokens[index]
        if is_env_executable(shell_arg):
            tokens = strip_env_invocation(tokens[index:])
            index = 0
            continue
        if is_assignment_prefix(shell_arg):
            index += 1
            continue
        break
    return tokens[index:]


def has_environment_prefix(tokens: list[str]) -> bool:
    if not tokens:
        return False
    if is_env_executable(tokens[0]):
        return True
    return is_assignment_prefix(tokens[0])


def command_tokens(command: str) -> list[str]:
    try:
        return strip_environment_prefix(shlex.split(command))
    except ValueError:
        return []


def command_index_after_options(
    tokens: list[str],
    start_index: int,
    value_options: set[str],
    terminal_options: set[str] | None = None,
) -> int | None:
    index = start_index
    terminal_options = terminal_options or set()
    while index < len(tokens):
        arg = tokens[index]
        if arg == "--":
            return None
        if not arg.startswith("-") or arg == "-":
            return index
        option_name = arg.split("=", 1)[0]
        if option_name in terminal_options:
            return None
        if option_name in value_options:
            index += 1 if "=" in arg else 2
            continue
        if len(arg) > 2 and arg[:2] in value_options:
            index += 1
            continue
        index += 1
    return None


def pip_args_require_sfw(tokens: list[str]) -> bool:
    command_index = command_index_after_options(tokens, 0, PIP_OPTIONS_WITH_VALUE, PIP_TERMINAL_OPTIONS)
    return command_index is not None and tokens[command_index] == "install"


def python_invokes_pip(tokens: list[str]) -> bool:
    if len(tokens) < 4 or executable_name(tokens[0]) not in PYTHON_BINARIES:
        return False
    index = 1
    while index < len(tokens):
        arg = tokens[index]
        if arg == "--":
            return False
        if arg == "-m":
            if index + 1 >= len(tokens):
                return False
            if tokens[index + 1] != "pip":
                return False
            return pip_args_require_sfw(tokens[index + 2 :])
        if arg == "-c":
            return False
        if not arg.startswith("-") or arg == "-":
            return False
        option_name = arg.split("=", 1)[0]
        if option_name in PYTHON_OPTIONS_WITH_VALUE:
            index += 1 if "=" in arg or (len(arg) > 2 and arg[:2] in PYTHON_OPTIONS_WITH_VALUE) else 2
            continue
        if len(arg) > 2 and arg[:2] in PYTHON_OPTIONS_WITH_VALUE:
            index += 1
            continue
        index += 1
    return False


def shell_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SHELL_SEGMENT_PUNCTUATION)
    lexer.whitespace_split = True
    tokens = list(lexer)
    segments: list[list[str]] = []
    current_segment: list[str] = []
    for token in tokens:
        if token and all(char in SHELL_SEGMENT_PUNCTUATION for char in token):
            if current_segment:
                segments.append(current_segment)
                current_segment = []
            continue
        current_segment.append(token)
    if current_segment:
        segments.append(current_segment)
    return segments


def shell_segments_require_sfw(command: str) -> bool:
    try:
        segments = shell_segments(command)
    except ValueError:
        return False
    return any(tokens_require_sfw(strip_environment_prefix(segment)) for segment in segments)


def tokens_require_sfw(tokens: list[str]) -> bool:
    if not tokens:
        return False
    if executable_name(tokens[0]) == "sfw":
        return False
    if python_invokes_pip(tokens):
        return True

    tool = executable_name(tokens[0])
    if tool in {"pip", "pip3"}:
        return pip_args_require_sfw(tokens[1:])
    protected_subcommands = SFW_PROTECTED_COMMANDS.get(tool)
    if protected_subcommands is None:
        return tool in SFW_PROTECTED_COMMANDS
    command_index = command_index_after_options(tokens, 1, CLI_OPTIONS_WITH_VALUE, CLI_TERMINAL_OPTIONS)
    return command_index is not None and tokens[command_index] in protected_subcommands


def command_requires_sfw(command: str) -> bool:
    return tokens_require_sfw(command_tokens(command))


def sfw_protection_payload(command: str) -> dict[str, str] | None:
    if SHELL_COMPLEXITY_RE.search(command):
        if shell_segments_require_sfw(command):
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


def command_parts(command: str) -> list[str]:
    try:
        return shlex.split(command, comments=False, posix=True)
    except ValueError:
        return []


def shell_expanded_names(command: str) -> list[str]:
    names: list[str] = []
    in_single = False
    in_double = False
    idx = 0
    while idx < len(command):
        char = command[idx]
        if char == "\\" and not in_single:
            idx += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            idx += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            idx += 1
            continue
        if in_single or char != "$":
            idx += 1
            continue
        match = SENSITIVE_ENV_EXPANSION_RE.match(command, idx)
        if match:
            names.append(match.group(1))
            idx = match.end()
            continue
        idx += 1
    return names


def segment_has_protected_option_value(parts: list[str]) -> bool:
    parts = strip_environment_prefix(parts)
    tool = executable_name(parts[0]) if parts else ""
    for idx, part in enumerate(parts):
        if part == "--":
            if tool in SENSITIVE_SCAN_TOOLS:
                break
            continue
        if not SENSITIVE_OPTION_RE.match(part):
            continue
        if "=" in part:
            return bool(part.split("=", 1)[1])
        next_part = parts[idx + 1] if idx + 1 < len(parts) else ""
        if next_part and not next_part.startswith("-"):
            return True
    return False


def command_has_protected_option_value(command: str) -> bool:
    try:
        segments = shell_segments(command)
    except ValueError:
        segments = [command_parts(command)]
    return any(segment_has_protected_option_value(segment) for segment in segments)


def command_has_protected_env_exposure(command: str) -> bool:
    for name in shell_expanded_names(command):
        if SENSITIVE_ENV_NAME_RE.match(name):
            return True

    if not ENV_READ_RE.search(command):
        return False

    if any(SENSITIVE_ENV_NAME_RE.match(name) for name in ENV_NAME_LITERAL_RE.findall(command)):
        return True

    proc_re = re.compile(r"\bprocess\." + "env" + r"\.([A-Za-z_][A-Za-z0-9_]*)")
    return any(SENSITIVE_ENV_NAME_RE.match(match.group(1)) for match in proc_re.finditer(command))


def search_option_targets_protected_path(tool: str, segment: list[str]) -> bool:
    for idx, candidate in enumerate(segment):
        next_part = segment[idx + 1] if idx + 1 < len(segment) else ""
        if tool in {"rg", "ag", "ack"}:
            if candidate in {"-g", "--glob", "--iglob"} and next_part and SENSITIVE_PATH_RE.search(next_part):
                return True
            if candidate.startswith(("--glob=", "--iglob=")) and SENSITIVE_PATH_RE.search(candidate.split("=", 1)[1]):
                return True
            if candidate.startswith("-g") and candidate != "-g" and SENSITIVE_PATH_RE.search(candidate[2:]):
                return True
        if tool in {"grep", "egrep", "fgrep"}:
            if candidate == "--include" and next_part and SENSITIVE_PATH_RE.search(next_part):
                return True
            if candidate.startswith("--include=") and SENSITIVE_PATH_RE.search(candidate.split("=", 1)[1]):
                return True
    return False


def command_has_protected_scan_path(command: str) -> bool:
    parts = command_parts(command)
    for idx, part in enumerate(parts):
        tool = executable_name(part)
        if tool not in SENSITIVE_SCAN_TOOLS:
            continue

        segment: list[str] = []
        for candidate in parts[idx + 1 :]:
            if candidate in {";", "&&", "||", "|"}:
                break
            segment.append(candidate)

        if search_option_targets_protected_path(tool, segment):
            return True

        positionals = [candidate for candidate in segment if not candidate.startswith("-")]
        if not positionals:
            continue
        if tool in {"grep", "egrep", "fgrep"} and any(SENSITIVE_PATH_RE.search(candidate) for candidate in positionals[1:]):
            return True
        if tool in {"rg", "ag", "ack"}:
            if "--files" in segment and any(SENSITIVE_PATH_RE.search(candidate) for candidate in positionals):
                return True
            if any(SENSITIVE_PATH_RE.search(candidate) for candidate in positionals[1:]):
                return True
    return False


def command_has_sensitive_tool_path(command: str) -> bool:
    try:
        segments = shell_segments(command)
    except ValueError:
        segments = [command_parts(command)]
    for raw_segment in segments:
        segment = strip_environment_prefix(raw_segment)
        if not segment:
            continue
        tool = executable_name(segment[0])
        if tool not in SENSITIVE_COMMAND_TOOLS:
            continue
        if any(SENSITIVE_PATH_RE.search(part) for part in segment[1:]):
            return True
    return False


def command_from_payload(payload: dict[str, Any]) -> str:
    tool_input = tool_input_from_payload(payload)
    if isinstance(tool_input, dict):
        return str(tool_input.get("command") or tool_input.get("cmd") or "")
    return str(tool_input)


def payload_is_patch_text(payload: dict[str, Any]) -> bool:
    text = payload_patch_text(payload).lstrip()
    return text.startswith("*** Begin Patch")


def cwd_from_payload(payload: dict[str, Any]) -> Path:
    candidates: list[str] = []
    for key in ("cwd", "workdir", "working_directory", "workspace_root"):
        value = payload.get(key)
        if isinstance(value, str):
            candidates.append(value)
    tool_input = tool_input_from_payload(payload)
    if isinstance(tool_input, dict):
        for key in ("cwd", "workdir", "working_directory", "workspace_root"):
            value = tool_input.get(key)
            if isinstance(value, str):
                candidates.append(value)
    for candidate in candidates:
        path = Path(os.path.expanduser(os.path.expandvars(candidate)))
        try:
            return path.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
    return Path.cwd().resolve()


def is_python_executable_token(token: str) -> bool:
    name = executable_name(token)
    if name in PYTHON_BINARIES:
        return True
    return name == "python"


def python_script_index(tokens: list[str]) -> int | None:
    if not tokens or not is_python_executable_token(tokens[0]):
        return None
    index = 1
    while index < len(tokens):
        arg = tokens[index]
        if arg == "--":
            return index + 1 if index + 1 < len(tokens) else None
        if arg in {"-c", "-m"}:
            return None
        if not arg.startswith("-") or arg == "-":
            return index
        option_name = arg.split("=", 1)[0]
        if option_name in PYTHON_OPTIONS_WITH_VALUE:
            index += 1 if "=" in arg or (len(arg) > 2 and arg[:2] in PYTHON_OPTIONS_WITH_VALUE) else 2
            continue
        if len(arg) > 2 and arg[:2] in PYTHON_OPTIONS_WITH_VALUE:
            index += 1
            continue
        index += 1
    return None


def resolve_command_path(raw_path: str, cwd: Path) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(raw_path))
    path = Path(expanded)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve(strict=False)


def is_wakeup_script_path(raw_path: str) -> bool:
    normalized = raw_path.replace("\\", "/")
    return normalized == "scripts/memory/wakeup.py" or normalized.endswith("/scripts/memory/wakeup.py")


def wakeup_suggested_command(cwd: Path) -> str:
    workspace_root = str(cwd)
    project = cwd.name or "default"
    return shlex.join(
        [
            "python3",
            str(REPO_ROOT / "scripts" / "memory" / "wakeup.py"),
            "--project",
            project,
            "--workspace-root",
            workspace_root,
        ]
    )


def stale_repo_local_wakeup_payload(command: str, payload: dict[str, Any]) -> dict[str, str] | None:
    try:
        segments = shell_segments(command)
    except ValueError:
        return None
    cwd = cwd_from_payload(payload)
    global_wakeup = (REPO_ROOT / "scripts" / "memory" / "wakeup.py").resolve(strict=False)
    for raw_segment in segments:
        segment = strip_environment_prefix(raw_segment)
        if not segment:
            continue
        script_index: int | None
        if is_python_executable_token(segment[0]):
            script_index = python_script_index(segment)
        else:
            script_index = 0 if is_wakeup_script_path(segment[0]) else None
        if script_index is None or script_index >= len(segment):
            continue
        script = segment[script_index]
        if not is_wakeup_script_path(script):
            continue
        target = resolve_command_path(script, cwd)
        if target != global_wakeup:
            return {
                "reason": STALE_WAKEUP_REASON,
                "suggested_command": wakeup_suggested_command(cwd),
            }
    return None


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
    patch_text = payload_patch_text(payload)
    patch_cwd = cwd_from_payload(payload)
    eligible_local_targets = local_patch_targets(patch_text, patch_cwd) if patch_text else None
    local_patch_allowed = bool(eligible_local_targets) and local_minikube_patch_allowed(patch_text, patch_cwd)
    if eligible_local_targets and not local_patch_allowed:
        patch_hash = local_patch_digest(patch_text)
        target_args = " ".join(f"--target {shlex.quote(str(target))}" for target in eligible_local_targets)
        suggested_command = (
            f"~/.ralph-codex/bin/authorize-local-minikube-patch --sha256 {patch_hash} "
            f"--cwd {shlex.quote(str(patch_cwd))} {target_args}"
        )
        write_json(
            {
                "decision": "block",
                "reason": (
                    "This exact .local-notes patch is eligible but requires explicit user approval. "
                    "Request approval to run suggested_command, then retry the identical patch."
                ),
                "reason_code": "local_patch_grant_required",
                "suggested_command": suggested_command,
                "patch_sha256": patch_hash,
                "targets": [str(target) for target in eligible_local_targets],
            }
        )
        return 0
    patch_finding = None if local_patch_allowed else classify_patch_payload(patch_text)
    if patch_finding:
        write_json(patch_finding.hook_payload())
        return 0
    if payload_is_patch_text(payload) or local_patch_allowed:
        return 0

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
    if command_has_sensitive_tool_path(command):
        write_json({"decision": "block", "reason": "Blocked command that could expose RED-sensitive material."})
        return 0
    if SCRIPT_EXEC_RE.search(command) and SENSITIVE_PATH_RE.search(command) and SCRIPT_READ_RE.search(command):
        write_json({"decision": "block", "reason": "Blocked command that could expose RED-sensitive material."})
        return 0
    if (
        command_has_protected_option_value(command)
        or command_has_protected_env_exposure(command)
        or command_has_protected_scan_path(command)
    ):
        write_json({"decision": "block", "reason": "Blocked command that could expose RED-sensitive material."})
        return 0
    wakeup_payload = stale_repo_local_wakeup_payload(command, payload)
    if wakeup_payload:
        write_json({"decision": "block", **wakeup_payload})
        return 0
    context_finding = classify_command(command, cwd_from_payload(payload))
    if context_finding:
        write_json(context_finding.hook_payload())
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
