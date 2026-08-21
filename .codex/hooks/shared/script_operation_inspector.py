from __future__ import annotations

import hashlib
import re
from pathlib import Path

SCRIPT_INTERPRETERS = {"bash", "node", "perl", "python", "python3", "ruby", "sh", "zsh"}
SCRIPT_SUFFIXES = {".bash", ".js", ".mjs", ".pl", ".py", ".rb", ".sh", ".zsh"}
SHELL_SCRIPT_SUFFIXES = {".bash", ".sh", ".zsh"}
LITERAL_SEARCH_TOOLS = {"grep", "rg"}
PYTHON_VALUE_OPTIONS = {"-W", "-X", "--check-hash-based-pycs"}
MAX_SCRIPT_BYTES = 256_000
TOOL_RE = re.compile(r"(?<![A-Za-z0-9_.-])(aws|gcloud|helm|kubectl|minikube|terraform)(?![A-Za-z0-9_.-])")


def _quoted_shell_span(line: str, offset: int) -> tuple[str, str] | None:
    """Return the quote kind and contents enclosing offset, if any."""

    quote = ""
    start = -1
    escaped = False
    for index, char in enumerate(line):
        if index == offset:
            if not quote:
                return None
            end = index
            inner_escaped = False
            while end < len(line):
                current = line[end]
                if quote == '"' and current == "\\" and not inner_escaped:
                    inner_escaped = True
                    end += 1
                    continue
                if current == quote and not inner_escaped:
                    return quote, line[start + 1 : end]
                inner_escaped = False
                end += 1
            return None
        if quote:
            if quote == '"' and char == "\\" and not escaped:
                escaped = True
                continue
            if char == quote and not escaped:
                quote = ""
                start = -1
            escaped = False
            continue
        if char in {"'", '"'}:
            quote = char
            start = index
    return None


def _contains_command_substitution(value: str, quote: str) -> bool:
    if quote == "'":
        return False
    escaped = False
    for index, char in enumerate(value):
        if char == "\\" and not escaped:
            escaped = True
            continue
        if not escaped and char == "`":
            return True
        if not escaped and char == "$" and index + 1 < len(value) and value[index + 1] == "(":
            return True
        escaped = False
    return False


def _literal_shell_search_reference(path: Path, line: str, offset: int) -> bool:
    """Identify cloud-tool names used only as literal grep/rg search data."""

    if path.suffix.lower() not in SHELL_SCRIPT_SUFFIXES:
        return False
    span = _quoted_shell_span(line, offset)
    if not span:
        return False
    quote, value = span
    if _contains_command_substitution(value, quote):
        return False
    leading = re.match(r"\s*(?:command\s+)?([^\s;&|()]+)", line)
    return bool(leading and Path(leading.group(1)).name in LITERAL_SEARCH_TOOLS)


def _is_script_interpreter(tool: str) -> bool:
    return tool in SCRIPT_INTERPRETERS or bool(re.fullmatch(r"python(?:3(?:\.\d+)*)?", tool))


def _regular_script(candidate: Path) -> Path | None:
    absolute = candidate.expanduser()
    if absolute.is_symlink():
        return None
    try:
        resolved = absolute.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_file() else None


def script_path(parts: list[str], cwd: Path) -> Path | None:
    if not parts:
        return None
    tool = Path(parts[0]).name.lower()
    is_interpreter = _is_script_interpreter(tool)
    if is_interpreter:
        index = 1
        while index < len(parts):
            part = parts[index]
            if part == "--":
                index += 1
                break
            if part in {"-c", "-m"}:
                return None
            option = part.split("=", 1)[0]
            if option in PYTHON_VALUE_OPTIONS:
                index += 1 if "=" in part or (len(part) > 2 and part[:2] in PYTHON_VALUE_OPTIONS) else 2
                continue
            if part.startswith("-"):
                index += 1
                continue
            break
        candidates = parts[index : index + 1]
    else:
        if "/" not in parts[0] and not Path(parts[0]).is_absolute():
            return None
        candidates = parts[:1]
    if not candidates:
        return None
    candidate = Path(candidates[0])
    candidate = candidate if candidate.is_absolute() else cwd / candidate
    script = _regular_script(candidate)
    if not script:
        return None
    if is_interpreter or script.suffix.lower() in SCRIPT_SUFFIXES or script.stat().st_mode & 0o111:
        return script
    return None


def wrapper_script_path(parts: list[str], cwd: Path) -> Path | None:
    value_options = {"--profile", "--context"}
    index = 1
    while index < len(parts):
        part = parts[index]
        if part in value_options:
            index += 2
            continue
        if any(part.startswith(option + "=") for option in value_options):
            index += 1
            continue
        candidate = Path(part)
        candidate = candidate if candidate.is_absolute() else cwd / candidate
        return _regular_script(candidate)
    return None


def script_cloud_commands(path: Path) -> tuple[list[str], str, str]:
    try:
        if path.stat().st_size > MAX_SCRIPT_BYTES:
            return ([], "script exceeds static inspection limit", "")
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ([], "script cannot be inspected as text", "")
    commands: list[str] = []
    for line in content.replace("\\\n", " ").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = TOOL_RE.search(stripped)
        if match and not _literal_shell_search_reference(path, stripped, match.start()):
            commands.append(stripped[match.start() :])
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return (commands, "", fingerprint)
