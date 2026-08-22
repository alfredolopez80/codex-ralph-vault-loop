from __future__ import annotations

import ast
import hashlib
import re
import shlex
from pathlib import Path

SCRIPT_INTERPRETERS = {"bash", "node", "perl", "python", "python3", "ruby", "sh", "zsh"}
SHELL_INTERPRETERS = {"bash", "sh", "zsh"}
SHELL_VALUE_OPTIONS = {"-O", "+O", "-o", "+o", "--init-file", "--rcfile"}
SCRIPT_SUFFIXES = {".bash", ".js", ".mjs", ".pl", ".py", ".rb", ".sh", ".zsh"}
SHELL_SCRIPT_SUFFIXES = {".bash", ".sh", ".zsh"}
PYTHON_VALUE_OPTIONS = {"-W", "-X", "--check-hash-based-pycs"}
MAX_SCRIPT_BYTES = 256_000
TOOL_RE = re.compile(r"(?<![A-Za-z0-9_.-])(aws|gcloud|helm|kubectl|minikube|terraform)(?![A-Za-z0-9_.-])")
CLOUD_TOOLS = frozenset({"aws", "gcloud", "helm", "kubectl", "minikube", "terraform"})
SHELL_CONTROL_WORDS = frozenset({"!", "{", "}", "do", "done", "elif", "else", "if", "then", "time", "until", "while"})
SHELL_NON_EXECUTING_COMMANDS = frozenset(
    {"[", "[[", "cat", "chmod", "cmp", "echo", "grep", "head", "printf", "readlink", "rg", "sed", "stat", "tail", "test", "touch", "tr", "wc"}
)
SHELL_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=.*", re.DOTALL)
SHELL_SUBSTITUTION_RE = re.compile(r"\$\((?P<dollar>[^()]*)\)|(?<!\\)`(?P<backtick>[^`]*)`")
SHELL_VARIABLE_RE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))")
SHELL_WRAPPERS = frozenset({"builtin", "command", "env", "exec", "nohup", "sudo", "xargs"})
SHELL_WRAPPER_VALUE_OPTIONS = {
    "env": frozenset({"-C", "-S", "-a", "-u", "--argv0", "--chdir", "--split-string", "--unset"}),
    "sudo": frozenset({"-C", "-D", "-R", "-T", "-U", "-g", "-h", "-p", "-r", "-t", "-u"}),
    "xargs": frozenset(
        {
            "-E",
            "-I",
            "-L",
            "-P",
            "-a",
            "-n",
            "-s",
            "--arg-file",
            "--eof",
            "--max-args",
            "--max-chars",
            "--max-lines",
            "--max-procs",
            "--replace",
        }
    ),
}
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


def _cloud_tool_token(value: str) -> str:
    tool = Path(value).name.lower()
    return tool if tool in CLOUD_TOOLS else ""


def _shell_segments(line: str) -> list[list[str]]:
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    segments: list[list[str]] = []
    current: list[str] = []
    for token in lexer:
        if token and all(char in ";&|()" for char in token):
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _shell_command_position(parts: list[str]) -> tuple[int, list[str]] | None:
    index = 0
    while index < len(parts) and parts[index] in SHELL_CONTROL_WORDS:
        index += 1
    assignments: list[str] = []
    while index < len(parts) and SHELL_ASSIGNMENT_RE.fullmatch(parts[index]):
        assignments.append(parts[index])
        index += 1
    return (index, assignments) if index < len(parts) else None


def _nested_command_position(parts: list[str], index: int, value_options: frozenset[str]) -> int | None:
    index += 1
    while index < len(parts):
        part = parts[index]
        option = part.split("=", 1)[0]
        if SHELL_ASSIGNMENT_RE.fullmatch(part):
            index += 1
            continue
        if option in value_options:
            index += 1 if "=" in part else 2
            continue
        if part == "--":
            index += 1
            continue
        if part.startswith("-"):
            index += 1
            continue
        return index
    return None


def _shell_command_text(parts: list[str], index: int) -> str:
    for option_index, part in enumerate(parts[index + 1 :], start=index + 1):
        if part == "-c" or (
            len(part) > 2 and part.startswith("-") and part[1:].isalpha() and "c" in part[1:]
        ):
            return parts[option_index + 1] if option_index + 1 < len(parts) else ""
    return ""


def _cloud_assignment_names(parts: list[str]) -> set[str]:
    names: set[str] = set()
    for part in parts:
        if not SHELL_ASSIGNMENT_RE.fullmatch(part):
            continue
        name, value = part.split("=", 1)
        if TOOL_RE.search(value) or _cloud_tool_token(value):
            names.add(name.rstrip("+"))
    return names


def _exact_variable_name(value: str) -> str:
    match = SHELL_VARIABLE_RE.fullmatch(value)
    return (match.group("braced") or match.group("plain")) if match else ""


def _segment_executes_cloud_binding(parts: list[str], names: set[str]) -> bool:
    position = _shell_command_position(parts)
    if not position:
        return False
    command_index, _ = position
    command = Path(parts[command_index]).name.lower()
    if command in SHELL_NON_EXECUTING_COMMANDS:
        return False
    return any(_exact_variable_name(part) in names for part in parts[command_index:])


def _dynamic_pipeline_with_cloud_text(line: str, segments: list[list[str]]) -> bool:
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    if not any(token == "|" for token in lexer):
        return False
    for parts in segments:
        position = _shell_command_position(parts)
        if not position:
            continue
        command_index, _ = position
        command = Path(parts[command_index]).name.lower()
        if command in SHELL_INTERPRETERS:
            if not shell_noexec(parts[command_index:]) and not _shell_command_text(parts, command_index):
                return True
        if command == "xargs" and any(
            Path(part).name.lower() in SHELL_INTERPRETERS for part in parts[command_index + 1 :]
        ):
            return True
    return False


def _env_split_command(parts: list[str], index: int) -> tuple[list[str] | None, str]:
    for option_index, part in enumerate(parts[index + 1 :], start=index + 1):
        if part in {"-S", "--split-string"}:
            if option_index + 1 >= len(parts):
                return ([], "env --split-string is missing its command value")
            value = parts[option_index + 1]
        elif part.startswith("--split-string="):
            value = part.split("=", 1)[1]
        elif part.startswith("-S") and part != "-S":
            value = part[2:]
        else:
            continue
        try:
            return (shlex.split(value, posix=True), "")
        except ValueError:
            return ([], "env --split-string contains shell content that cannot be parsed statically")
    return (None, "")


def _dynamic_cloud_substitution(line: str) -> tuple[list[str], str]:
    commands: list[str] = []
    for match in SHELL_SUBSTITUTION_RE.finditer(line):
        command_text = match.group("dollar") if match.group("dollar") is not None else match.group("backtick")
        if not command_text:
            continue
        span = _quoted_shell_span(line, match.start())
        if span and span[0] == "'":
            continue
        try:
            segments = _shell_segments(command_text)
        except ValueError:
            if TOOL_RE.search(command_text):
                return ([], "script contains cloud-tool text in an unparseable command substitution")
            continue
        for segment in segments:
            command, error = _shell_segment_cloud_command(segment, depth=1)
            if error:
                return ([], error)
            if command:
                commands.append(command)
    return (commands, "")


def _shell_segment_cloud_command(parts: list[str], depth: int = 0) -> tuple[str, str]:
    if depth > 3:
        return ("", "script contains nested shell execution beyond the static inspection limit")
    position = _shell_command_position(parts)
    if not position:
        return ("", "")
    command_index, assignments = position
    command = Path(parts[command_index]).name.lower()
    if _cloud_tool_token(parts[command_index]):
        return (shlex.join([*assignments, *parts[command_index:]]), "")

    if command in SHELL_INTERPRETERS:
        command_text = _shell_command_text(parts, command_index)
        if command_text and TOOL_RE.search(command_text):
            return (shlex.join(parts[command_index:]), "")
        if any(_cloud_tool_token(part) for part in parts[command_index + 1 :]):
            return ("", "shell receives a cloud-tool token through a non-command argument")
        return ("", "")

    if command in SHELL_WRAPPERS:
        if command == "env":
            split_command, split_error = _env_split_command(parts, command_index)
            if split_error:
                return ("", split_error)
            if split_command is not None:
                return _shell_segment_cloud_command(split_command, depth + 1)
        value_options = SHELL_WRAPPER_VALUE_OPTIONS.get(command, frozenset())
        nested = _nested_command_position(parts, command_index, value_options)
        if nested is None:
            return ("", "")
        nested_command, nested_error = _shell_segment_cloud_command(parts[nested:], depth + 1)
        if nested_error:
            return ("", nested_error)
        if nested_command:
            if command in {"env", "xargs"}:
                return (shlex.join(parts[command_index:]), "")
            return (nested_command, "")
        return ("", "")

    if command == "eval":
        rendered = " ".join(parts[command_index + 1 :])
        if not rendered:
            return ("", "")
        try:
            nested_segments = _shell_segments(rendered)
        except ValueError:
            return ("", "eval contains shell content that cannot be parsed statically")
        for nested_parts in nested_segments:
            nested_command, nested_error = _shell_segment_cloud_command(nested_parts, depth + 1)
            if nested_command or nested_error:
                return (nested_command, nested_error)
        if TOOL_RE.search(rendered):
            return ("", "eval contains unresolved cloud-tool execution")
        return ("", "")

    if command == "find":
        for index, part in enumerate(parts[command_index + 1 :], start=command_index + 1):
            if part not in {"-exec", "-execdir"} or index + 1 >= len(parts):
                continue
            nested_command, nested_error = _shell_segment_cloud_command(parts[index + 1 :], depth + 1)
            if nested_command or nested_error:
                return (nested_command, nested_error)

    if command in SHELL_NON_EXECUTING_COMMANDS:
        return ("", "")
    if any(_cloud_tool_token(part) for part in parts[command_index + 1 :]):
        return ("", "script passes a cloud-tool token through an unrecognized shell execution form")
    matching_arguments = [part for part in parts[command_index + 1 :] if TOOL_RE.search(part)]
    if matching_arguments and not all("/" in part for part in matching_arguments):
        return ("", "script contains cloud-tool text in an unrecognized shell execution form")
    return ("", "")


def _shell_cloud_commands(content: str, *, inspect_outer: bool = True) -> tuple[list[str], str]:
    commands: list[str] = []
    cloud_bindings: set[str] = set()
    for raw_line in content.replace("\\\n", " ").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            segments = _shell_segments(line)
        except ValueError:
            if TOOL_RE.search(line):
                return ([], "script contains cloud-tool text in shell syntax that cannot be parsed statically")
            continue
        for segment in segments:
            cloud_bindings.update(_cloud_assignment_names(segment))
        if any(_segment_executes_cloud_binding(segment, cloud_bindings) for segment in segments):
            return ([], "script executes a cloud-tool value through dynamic shell data flow")
        substitution_commands, substitution_error = _dynamic_cloud_substitution(line)
        if substitution_error:
            return ([], substitution_error)
        commands.extend(substitution_commands)
        if inspect_outer:
            for segment in segments:
                command, error = _shell_segment_cloud_command(segment)
                if error:
                    return ([], error)
                if command:
                    commands.append(command)
        if TOOL_RE.search(line) and _dynamic_pipeline_with_cloud_text(line, segments):
            has_direct_cloud_command = any(
                _cloud_tool_token(segment[_shell_command_position(segment)[0]])
                for segment in segments
                if _shell_command_position(segment)
            )
            if not has_direct_cloud_command:
                return ([], "script pipes cloud-tool data into a dynamic shell execution form")
    return (commands, "")


def inline_shell_cloud_commands(content: str) -> tuple[list[str], str]:
    """Return only nested or dynamic cloud behavior from an inline command."""

    return _shell_cloud_commands(content, inspect_outer=False)


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


def _python_local_call_fragments(
    tree: ast.AST,
    node: ast.AST,
    bindings: dict[str, ast.AST],
    aliases: dict[str, str],
) -> list[str]:
    if not isinstance(node, ast.Call) or node.args or node.keywords or not isinstance(node.func, ast.Name):
        return []
    for candidate in ast.walk(tree):
        if not isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)) or candidate.name != node.func.id:
            continue
        return [
            fragment
            for child in ast.walk(candidate)
            if isinstance(child, ast.Return) and child.value is not None
            for fragment in _python_command_fragments(child.value, bindings, aliases)
        ]
    return []


def _python_cloud_commands(content: str) -> tuple[list[str], str] | None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    aliases = _python_aliases(tree)
    bindings = _python_bindings(tree)
    commands: list[str] = []
    unresolved_process_call = False
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
        if not fragments:
            fragments = _python_local_call_fragments(tree, node.args[0], bindings, aliases)
        if not fragments:
            source = ast.get_source_segment(content, node.args[0]) or ""
            unresolved_process_call = unresolved_process_call or bool(TOOL_RE.search(source))
            continue
        rendered = " ".join(fragments)
        match = TOOL_RE.search(rendered)
        if match:
            commands.append(rendered[match.start() :])
    if unresolved_process_call and TOOL_RE.search(content):
        return ([], "python process execution derives from unresolved cloud-tool content")
    return (commands, "")


def script_cloud_commands(path: Path, *, shell_hint: bool = False) -> tuple[list[str], str, str]:
    try:
        if path.stat().st_size > MAX_SCRIPT_BYTES:
            return ([], "script exceeds static inspection limit", "")
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ([], "script cannot be inspected as text", "")
    python_analysis = _python_cloud_commands(content) if path.suffix.lower() == ".py" else None
    if python_analysis is not None:
        commands, error = python_analysis
    elif shell_hint or path.suffix.lower() in SHELL_SCRIPT_SUFFIXES:
        commands, error = _shell_cloud_commands(content)
    elif TOOL_RE.search(content):
        commands, error = ([], "non-shell script contains cloud-tool execution that cannot be proven statically")
    else:
        commands, error = ([], "")
    if error:
        fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return ([], error, fingerprint)
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return (commands, "", fingerprint)
