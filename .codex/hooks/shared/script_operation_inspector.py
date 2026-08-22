from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

SCRIPT_INTERPRETERS = {"bash", "node", "perl", "python", "python3", "ruby", "sh", "zsh"}
SHELL_INTERPRETERS = {"bash", "sh", "zsh"}
SHELL_VALUE_OPTIONS = {"-O", "+O", "-o", "+o", "--init-file", "--rcfile"}
SCRIPT_SUFFIXES = {".bash", ".js", ".mjs", ".pl", ".py", ".rb", ".sh", ".zsh"}
SHELL_SCRIPT_SUFFIXES = {".bash", ".sh", ".zsh"}
LITERAL_SEARCH_TOOLS = {"grep", "rg"}
PYTHON_VALUE_OPTIONS = {"-W", "-X", "--check-hash-based-pycs"}
MAX_SCRIPT_BYTES = 256_000
TOOL_RE = re.compile(r"(?<![A-Za-z0-9_.-])(aws|gcloud|helm|kubectl|minikube|terraform)(?![A-Za-z0-9_.-])")
PYTHON_PROCESS_CALLS = {
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "os.popen",
    "os.system",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
    "subprocess.Popen",
    "subprocess.run",
}


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


def shell_noexec(parts: list[str]) -> bool:
    """Return whether a shell invocation keeps execution disabled.

    Shells process ``-n``/``+n`` left to right. Value-bearing options must be
    skipped so their operands are never mistaken for a script or another flag.
    """

    if not parts or Path(parts[0]).name.lower() not in SHELL_INTERPRETERS:
        return False
    noexec = False
    index = 1
    while index < len(parts):
        part = parts[index]
        if part == "--":
            break
        option = part.split("=", 1)[0]
        if option in {"-o", "+o"}:
            value = part.split("=", 1)[1] if "=" in part else (parts[index + 1] if index + 1 < len(parts) else "")
            if value == "noexec":
                noexec = option == "-o"
            index += 1 if "=" in part else 2
            continue
        if option in SHELL_VALUE_OPTIONS:
            index += 1 if "=" in part else 2
            continue
        if part.startswith("--"):
            index += 1
            continue
        if len(part) > 1 and part[0] in {"-", "+"} and part[1:].isalpha():
            flags = part[1:]
            if "n" in flags:
                noexec = part[0] == "-"
            if "c" in flags:
                break
            index += 1
            continue
        break
    return noexec


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
    is_shell = tool in SHELL_INTERPRETERS
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
            if is_shell and option in SHELL_VALUE_OPTIONS:
                index += 1 if "=" in part else 2
                continue
            if is_shell and len(part) > 1 and part[0] == "+" and part[1:].isalpha():
                index += 1
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


def _python_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _python_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _python_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".", 1)[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _resolved_python_name(node: ast.AST, aliases: dict[str, str]) -> str:
    value = _python_name(node)
    head, separator, tail = value.partition(".")
    replacement = aliases.get(head, head)
    return replacement + (separator + tail if separator else "")


def _python_bindings(tree: ast.AST) -> dict[str, ast.AST]:
    bindings: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            bindings[node.target.id] = node.value
    return bindings


def _python_command_fragments(
    node: ast.AST,
    bindings: dict[str, ast.AST],
    aliases: dict[str, str],
    seen: frozenset[str] = frozenset(),
) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
        return _python_command_fragments(bindings[node.id], bindings, aliases, seen | {node.id})
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [
            fragment
            for item in node.elts
            for fragment in _python_command_fragments(item, bindings, aliases, seen)
        ]
    if isinstance(node, ast.JoinedStr):
        return [
            fragment
            for item in node.values
            for fragment in _python_command_fragments(item, bindings, aliases, seen)
        ]
    if isinstance(node, ast.FormattedValue):
        return _python_command_fragments(node.value, bindings, aliases, seen)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _python_command_fragments(node.left, bindings, aliases, seen) + _python_command_fragments(
            node.right, bindings, aliases, seen
        )
    if isinstance(node, ast.Call) and _resolved_python_name(node.func, aliases) in {"shlex.split", "str"} and node.args:
        return _python_command_fragments(node.args[0], bindings, aliases, seen)
    return []


def _python_cloud_commands(content: str) -> list[str] | None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    aliases = _python_aliases(tree)
    bindings = _python_bindings(tree)
    commands: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolved_python_name(node.func, aliases)
        is_process_call = (
            call_name in PYTHON_PROCESS_CALLS
            or call_name.startswith("os.exec")
            or call_name.startswith("os.spawn")
        )
        if not is_process_call or not node.args:
            continue
        fragments = _python_command_fragments(node.args[0], bindings, aliases)
        rendered = " ".join(fragments)
        match = TOOL_RE.search(rendered)
        if match:
            commands.append(rendered[match.start() :])
    return commands


def script_cloud_commands(path: Path) -> tuple[list[str], str, str]:
    try:
        if path.stat().st_size > MAX_SCRIPT_BYTES:
            return ([], "script exceeds static inspection limit", "")
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ([], "script cannot be inspected as text", "")
    commands = _python_cloud_commands(content) if path.suffix.lower() == ".py" else None
    if commands is None:
        commands = []
        for line in content.replace("\\\n", " ").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = TOOL_RE.search(stripped)
            if match and not _literal_shell_search_reference(path, stripped, match.start()):
                commands.append(stripped[match.start() :])
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return (commands, "", fingerprint)
