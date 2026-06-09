from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .redaction import is_red


DATA_IMAGE_RE = re.compile(r"data:image/[^;,\s]+;base64,", re.IGNORECASE)
BASE64_RE = re.compile(r"(?:data:[a-zA-Z0-9.+/-]+/[a-zA-Z0-9.+/-]+;base64,)?[A-Za-z0-9+/]{4000,}={0,2}")
DEFAULT_LONG_LINE_LIMIT = int(os.environ.get("RALPH_CONTEXT_BUDGET_LONG_LINE_LIMIT", "200000"))
DEFAULT_MAX_DISPLAY_BYTES = int(os.environ.get("RALPH_CONTEXT_BUDGET_MAX_DISPLAY_BYTES", "60000"))
DEFAULT_MAX_PATCH_CHARS = int(os.environ.get("RALPH_CONTEXT_BUDGET_MAX_PATCH_CHARS", "250000"))

BINARY_LIKE_SUFFIXES = {
    ".7z",
    ".avif",
    ".db",
    ".dmg",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".sqlite",
    ".tar",
    ".tgz",
    ".webp",
    ".zip",
}
DISPLAY_COMMANDS = {"cat", "bat", "less", "more"}
HIGH_RISK_ROOT_NAMES = {".codex", ".agents", ".ralph-codex"}
NOISY_DIR_NAMES = {".git", "node_modules", "dist", "build", ".next", ".cache", "__pycache__"}
SHELL_SEGMENT_PUNCTUATION = ";&|()`"
BYTE_CAP_RE = re.compile(r"\|\s*(?:head\s+-c\s+\d+|dd\s+bs=\d+\s+count=\d+)\b")
LINE_CAP_RE = re.compile(r"\|\s*head\s+-(?:n\s+)?\d+\b")
SED_RANGE_RE = re.compile(r"\bsed\s+-n\s+['\"]?\d+,\d+p['\"]?")
TAIL_LINES_RE = re.compile(r"\btail\s+-(?:n\s+)?\d+\b")
OUTPUT_REDIRECT_RE = re.compile(r"(?:^|\s)(?:>\s*|1>\s*|2>\s*|&>\s*|2>&1\s*>)\S+")
BOUNDED_INSPECTION_RE = re.compile(r"(?:\|\s*head\s+-(?:c\s+\d+|(?:n\s+)?\d+)\b|\|\s*sed\s+-n\s+['\"]?\d+,\d+p['\"]?|\|\s*tail\s+-(?:n\s+)?\d+\b)")
ENV_OPTIONS_WITH_VALUE = {"-u", "--unset", "-C", "--chdir", "-P", "-a", "--argv0"}
ENV_OPTIONS_WITHOUT_VALUE = {"-0", "-i", "-v", "--ignore-environment", "--null"}
RG_OPTIONS_WITH_VALUE = {
    "-A",
    "-B",
    "-C",
    "-e",
    "-f",
    "-g",
    "-m",
    "-t",
    "-T",
    "--after-context",
    "--before-context",
    "--context",
    "--engine",
    "--glob",
    "--ignore-file",
    "--max-count",
    "--max-depth",
    "--max-filesize",
    "--path-separator",
    "--regexp",
    "--sort",
    "--threads",
    "--type",
    "--type-add",
    "--type-not",
}
RG_BOUNDS = {"-g", "-m", "--glob", "--max-count", "--max-filesize", "--files-with-matches", "-l"}
GREP_OPTIONS_WITH_VALUE = {"-A", "-B", "-C", "-e", "-f", "-m", "--after-context", "--before-context", "--context", "--file", "--max-count", "--regexp"}
VALIDATION_SCRIPT_NAMES = {
    "coding_model_eval.py",
    "context_guard_autoresearch_benchmark.py",
    "doctor-global.sh",
    "doctor.sh",
    "run-gates.py",
    "smoke-global-hooks.py",
    "validate-ralph-memory-flow.sh",
}
VALIDATION_COMMAND_NAMES = {"mypy", "pytest", "ruff", "shellcheck"}


@dataclass(frozen=True)
class GuardFinding:
    risk: str
    reason_code: str
    reason: str
    suggested_command: str | None = None

    def hook_payload(self) -> dict[str, str]:
        payload = {"decision": "block", "reason": self.reason}
        if self.suggested_command:
            payload["suggested_command"] = self.suggested_command
        return payload


def _executable_name(word: str) -> str:
    return Path(word).name.lower()


def _shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _shell_token_segments(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=SHELL_SEGMENT_PUNCTUATION)
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        words = _shell_tokens(command)
    segments: list[list[str]] = []
    current: list[str] = []
    for word in words:
        if word and all(char in SHELL_SEGMENT_PUNCTUATION for char in word):
            if current:
                segments.append(current)
                current = []
            continue
        current.append(word)
    if current:
        segments.append(current)
    return segments


def _is_assignment_prefix(word: str) -> bool:
    return "=" in word and not word.startswith("-") and bool(word.split("=", 1)[0])


def _strip_env_invocation(words: list[str]) -> list[str]:
    index = 1
    while index < len(words):
        word = words[index]
        if word == "--":
            return words[index + 1 :]
        if word in ENV_OPTIONS_WITHOUT_VALUE:
            index += 1
            continue
        option_name = word.split("=", 1)[0]
        if option_name in ENV_OPTIONS_WITH_VALUE:
            index += 1 if "=" in word else 2
            continue
        if _is_assignment_prefix(word):
            index += 1
            continue
        if word.startswith("-"):
            index += 1
            continue
        return words[index:]
    return []


def _strip_environment_prefix(words: list[str]) -> list[str]:
    while words:
        if _is_assignment_prefix(words[0]):
            words = words[1:]
            continue
        if _executable_name(words[0]) == "env":
            words = _strip_env_invocation(words)
            continue
        break
    return words


def _resolve_path(raw_path: str, cwd: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(raw_path))
    path = Path(expanded)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve(strict=False)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_range_command(path: Path) -> str:
    return shlex.join(["sed", "-n", "1,160p", str(path)])


def _safe_byte_cap_command(command: str) -> str:
    return f"{command.rstrip()} 2>&1 | head -c 6000"


def _has_output_cap(command: str) -> bool:
    return bool(
        BYTE_CAP_RE.search(command)
        or LINE_CAP_RE.search(command)
        or SED_RANGE_RE.search(command)
        or TAIL_LINES_RE.search(command)
        or BOUNDED_INSPECTION_RE.search(command)
    )


def _has_output_redirect(command: str) -> bool:
    return bool(OUTPUT_REDIRECT_RE.search(command))


def _has_redirected_bounded_inspection(command: str) -> bool:
    return _has_output_redirect(command) and bool(re.search(r"\bhead\s+-c\s+\d+\b|\bhead\s+-(?:n\s+)?\d+\b|\bsed\s+-n\s+['\"]?\d+,\d+p['\"]?|\btail\s+-(?:n\s+)?\d+\b", command))


def _has_any_bound(command: str) -> bool:
    return _has_output_cap(command) or _has_redirected_bounded_inspection(command)


def _segment_bound_text(segment_command: str, full_command: str) -> str:
    if _has_any_bound(segment_command):
        return segment_command
    if _has_output_cap(full_command) and "|" in full_command and not any(separator in full_command for separator in (";", "&&", "||")):
        return full_command
    if _has_redirected_bounded_inspection(full_command) and re.search(r"(?:^|\s)'?(?:&?>|[12]>)'?(?:\s|$)", segment_command):
        return full_command
    if _has_output_redirect(segment_command) and _has_redirected_bounded_inspection(full_command):
        return full_command
    return segment_command


def toxic_text_reasons(text: str, *, line_limit: int = DEFAULT_LONG_LINE_LIMIT) -> list[str]:
    reasons: list[str] = []
    if not text:
        return reasons
    if DATA_IMAGE_RE.search(text):
        reasons.append("inline data image base64")
    elif BASE64_RE.search(text):
        reasons.append("very long base64-like payload")
    if "replacement_history" in text and text.count("replacement_history") >= 3:
        reasons.append("repeated generated replacement history")
    for line in text.splitlines() or [text]:
        if len(line) > line_limit:
            reasons.append("single line exceeds safe transcript length")
            break
    if is_red(text):
        reasons.append("red-sensitive content")
    return reasons


def text_is_toxic(text: str) -> bool:
    return bool(toxic_text_reasons(text))


def classify_prompt(prompt: str) -> GuardFinding | None:
    reasons = toxic_text_reasons(prompt)
    if not reasons:
        return None
    return GuardFinding(
        risk="block",
        reason_code="toxic_prompt_payload",
        reason=(
            "Context budget guard blocked a prompt containing inline base64, RED-sensitive, "
            "or oversized payload. Save the artifact to disk and ask Codex to inspect targeted snippets."
        ),
    )


def classify_patch_payload(patch: str) -> GuardFinding | None:
    if not patch:
        return None
    if len(patch) > DEFAULT_MAX_PATCH_CHARS or toxic_text_reasons(patch):
        return GuardFinding(
            risk="block",
            reason_code="toxic_patch_payload",
            reason="Context budget guard blocked an oversized or toxic patch payload.",
        )
    return None


def _file_display_finding(path: Path) -> GuardFinding | None:
    suffix = path.suffix.lower()
    if suffix in BINARY_LIKE_SUFFIXES:
        return GuardFinding(
            risk="block",
            reason_code="binary_display",
            reason="Context budget guard blocked a command that may dump binary or media content into the transcript.",
        )
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > DEFAULT_MAX_DISPLAY_BYTES:
        return GuardFinding(
            risk="block",
            reason_code="large_file_display",
            reason="Context budget guard blocked a full-file display of an oversized artifact.",
            suggested_command=_safe_range_command(path),
        )
    return None


def _classify_display_command(tokens: list[str], cwd: Path) -> GuardFinding | None:
    if not tokens or _executable_name(tokens[0]) not in DISPLAY_COMMANDS:
        return None
    paths: list[Path] = []
    for word in tokens[1:]:
        if word.startswith("-"):
            continue
        paths.append(_resolve_path(word, cwd))
    for path in paths:
        finding = _file_display_finding(path)
        if finding:
            return finding
    return None


def _classify_base64(tokens: list[str]) -> GuardFinding | None:
    if not tokens or _executable_name(tokens[0]) != "base64":
        return None
    if any(token in {"-d", "--decode"} for token in tokens[1:]):
        return None
    return GuardFinding(
        risk="block",
        reason_code="base64_encode_transcript",
        reason="Context budget guard blocked a command that appears to emit base64 into the transcript.",
    )


def _rg_has_bound(tokens: list[str]) -> bool:
    return any(token in RG_BOUNDS or token.startswith("--glob=") or token.startswith("--max-count=") for token in tokens)


def _rg_operands(tokens: list[str]) -> list[str]:
    operands: list[str] = []
    index = 1
    while index < len(tokens):
        word = tokens[index]
        if word == "--":
            operands.extend(tokens[index + 1 :])
            break
        option_name = word.split("=", 1)[0]
        if word.startswith("-"):
            if option_name in RG_OPTIONS_WITH_VALUE and "=" not in word:
                index += 2
            else:
                index += 1
            continue
        operands.append(word)
        index += 1
    return operands


def _option_present(tokens: list[str], names: set[str]) -> bool:
    return any(token in names or any(token.startswith(name + "=") for name in names if name.startswith("--")) for token in tokens)


def _limited_numeric_option(tokens: list[str], names: set[str]) -> bool:
    for index, token in enumerate(tokens):
        option_name = token.split("=", 1)[0]
        if option_name in names:
            if "=" in token:
                return bool(token.split("=", 1)[1])
            return index + 1 < len(tokens)
        if token.startswith("-n") and len(token) > 2 and token[2:].isdigit():
            return True
    return False


def _is_repo_validation_script(raw_path: str, cwd: Path) -> bool:
    if Path(raw_path).name not in VALIDATION_SCRIPT_NAMES:
        return False
    resolved = _resolve_path(raw_path, cwd)
    return _is_relative_to(resolved, cwd.resolve(strict=False))


def _is_wakeup_script_path(raw_path: str) -> bool:
    normalized = raw_path.replace("\\", "/")
    return normalized == "scripts/memory/wakeup.py" or normalized.endswith("/scripts/memory/wakeup.py")


def _is_validation_command(tokens: list[str], cwd: Path) -> bool:
    if not tokens:
        return False
    executable = _executable_name(tokens[0])
    if executable in VALIDATION_COMMAND_NAMES:
        return True
    if executable in VALIDATION_SCRIPT_NAMES and _is_repo_validation_script(tokens[0], cwd):
        return True
    if executable in {"bash", "sh", "zsh"} and len(tokens) > 1:
        return _is_repo_validation_script(tokens[1], cwd)
    if executable in {"python", "python3"}:
        if "-m" in tokens:
            module_index = tokens.index("-m")
            if module_index + 1 < len(tokens) and tokens[module_index + 1] in {"pytest", "mypy"}:
                return True
        index = 1
        while index < len(tokens):
            word = tokens[index]
            if word == "--":
                index += 1
                break
            if not word.startswith("-"):
                break
            index += 1
        return index < len(tokens) and _is_repo_validation_script(tokens[index], cwd)
    return False


def _is_high_risk_rg_target(path: Path, cwd: Path) -> bool:
    home = Path.home().resolve()
    if path == Path("/"):
        return True
    if path == home:
        return True
    if any(part in NOISY_DIR_NAMES for part in path.parts):
        return True
    if _is_relative_to(path, cwd):
        return False
    if _is_relative_to(path, home / ".codex") or _is_relative_to(path, home / ".agents") or _is_relative_to(path, home / ".ralph-codex"):
        return True
    # The active repository itself remains a normal engineering target unless
    # paired with stronger risk signals such as -uuu or noisy generated paths.
    return False


def _classify_rg_command(tokens: list[str], cwd: Path) -> GuardFinding | None:
    if not tokens or _executable_name(tokens[0]) != "rg":
        return None
    operands = _rg_operands(tokens)
    targets = operands[1:] if len(operands) > 1 else ["."]
    resolved_targets = [_resolve_path(target, cwd) for target in targets]
    risky_target = any(_is_high_risk_rg_target(path, cwd) for path in resolved_targets)
    broad_flags = any(token in {"-uuu", "--hidden", "--no-ignore", "--no-ignore-vcs"} for token in tokens)
    if risky_target and (broad_flags or not _rg_has_bound(tokens)):
        return GuardFinding(
            risk="block",
            reason_code="broad_rg_high_risk_root",
            reason="Context budget guard blocked a broad search over a high-risk or noisy root. Use a scoped path, glob, or max-count.",
            suggested_command="rg -n --max-count 50 '<pattern>' <scoped-path>",
        )
    return None


def _classify_git_command(tokens: list[str], cwd: Path, command: str) -> GuardFinding | None:
    if not tokens or _executable_name(tokens[0]) != "git" or _has_any_bound(command):
        return None
    subcommand_index = 1
    while subcommand_index < len(tokens) and tokens[subcommand_index].startswith("-"):
        subcommand_index += 2 if tokens[subcommand_index] in {"-C", "--git-dir", "--work-tree"} else 1
    if subcommand_index >= len(tokens):
        return None
    subcommand = tokens[subcommand_index]
    args = tokens[subcommand_index + 1 :]
    if subcommand == "status":
        if _option_present(args, {"--short", "--porcelain"}) or any(arg in {"-s", "-sb", "-bs"} for arg in args):
            return None
        return GuardFinding(
            risk="block",
            reason_code="git_status_unbounded",
            reason="Context budget guard blocked verbose git status. Use porcelain or short output.",
            suggested_command="git status --porcelain | head -n 30",
        )
    if subcommand == "log":
        if _option_present(args, {"--oneline", "--max-count"}) or _limited_numeric_option(args, {"-n", "--max-count"}):
            return None
        return GuardFinding(
            risk="block",
            reason_code="git_log_unbounded",
            reason="Context budget guard blocked unbounded git log output. Use --oneline and an explicit limit.",
            suggested_command="git log --oneline -15",
        )
    if subcommand == "diff":
        if _option_present(args, {"--name-only", "--stat", "--name-status", "--summary", "--check"}):
            return None
        if "--" in args:
            scoped_args = [item for item in args[args.index("--") + 1 :] if not item.startswith("-")]
            if scoped_args and not any(_is_broad_diff_scope(item, cwd) for item in scoped_args):
                return None
        path_like_args = [
            arg
            for arg in args
            if not arg.startswith("-")
            and not _is_broad_diff_scope(arg, cwd)
            and (_resolve_path(arg, cwd).exists() or "/" in arg or Path(arg).suffix)
        ]
        if path_like_args:
            return None
        return GuardFinding(
            risk="block",
            reason_code="git_diff_unbounded",
            reason="Context budget guard blocked broad git diff output. Use --name-only, --stat, a path scope, or a byte cap.",
            suggested_command="git diff --name-only | head -n 50",
        )
    return None


def _is_broad_diff_scope(raw_path: str, cwd: Path) -> bool:
    normalized = raw_path.strip()
    if normalized in {".", "./", ":/", "/", "~", "$HOME"}:
        return True
    if normalized.startswith(":/"):
        return normalized == ":/"
    resolved = _resolve_path(normalized, cwd)
    home = Path.home().resolve()
    return resolved == cwd.resolve(strict=False) or resolved == home


def _find_has_bound(argv: list[str], command: str) -> bool:
    return (
        _has_any_bound(command)
        or any(arg in {"-maxdepth", "-prune", "-quit"} or arg.startswith("-maxdepth") for arg in argv[1:])
        or _limited_numeric_option(argv, {"--limit"})
    )


def _classify_recursive_listing(argv: list[str], cwd: Path, command: str) -> GuardFinding | None:
    if not argv:
        return None
    executable = _executable_name(argv[0])
    if executable == "ls" and any(arg.startswith("-") and "R" in arg for arg in argv[1:]):
        if _has_any_bound(command):
            return None
        return GuardFinding(
            risk="block",
            reason_code="recursive_listing",
            reason="Context budget guard blocked an unbounded recursive listing. Use a scoped repo map or byte-capped command.",
            suggested_command=_safe_byte_cap_command(command),
        )
    if executable == "ls":
        paths = [arg for arg in argv[1:] if not arg.startswith("-")]
        broad_listing = any(arg.startswith("-") and ("a" in arg or "l" in arg) for arg in argv[1:])
        targets = paths or ["."]
        risky = any(target == "/" or target in {".", "~", "$HOME"} or any(part in NOISY_DIR_NAMES for part in _resolve_path(target, cwd).parts) for target in targets)
        if broad_listing and risky and not _has_any_bound(command):
            return GuardFinding(
                risk="block",
                reason_code="broad_ls",
                reason="Context budget guard blocked broad ls output over a risky or noisy root. Use a scoped path or byte cap.",
                suggested_command=_safe_byte_cap_command(command),
            )
    if executable != "find":
        return None
    if _find_has_bound(argv, command):
        return None
    raw_targets = [arg for arg in argv[1:] if not arg.startswith("-")]
    targets = raw_targets[:1] if raw_targets else ["."]
    broad_default = any(target in {".", "./", "/", "~", "$HOME"} for target in targets)
    if broad_default or any(_is_high_risk_rg_target(_resolve_path(target, cwd), cwd) for target in targets):
        return GuardFinding(
            risk="block",
            reason_code="broad_find",
            reason="Context budget guard blocked a broad find over a high-risk or noisy root. Use -maxdepth, a scoped path, or a byte cap.",
            suggested_command="find . -maxdepth 3 -type f | sed 's#^\\./##' | sort | head -n 120",
        )
    return None


def _classify_grep_command(argv: list[str], cwd: Path, command: str) -> GuardFinding | None:
    if not argv or _executable_name(argv[0]) not in {"grep", "egrep", "fgrep"} or _has_any_bound(command):
        return None
    if _limited_numeric_option(argv, {"-m", "--max-count"}):
        return None
    operands: list[str] = []
    index = 1
    while index < len(argv):
        arg = argv[index]
        option_name = arg.split("=", 1)[0]
        if arg == "--":
            operands.extend(argv[index + 1 :])
            break
        if arg.startswith("-"):
            index += 2 if option_name in GREP_OPTIONS_WITH_VALUE and "=" not in arg else 1
            continue
        operands.append(arg)
        index += 1
    targets = operands[1:] if len(operands) > 1 else []
    broad_recursive = any("R" in arg or "r" in arg for arg in argv if arg.startswith("-"))
    broad_targets = not targets or any(target in {".", "./", "/", "~", "$HOME"} for target in targets)
    risky_target = any(_is_high_risk_rg_target(_resolve_path(target, cwd), cwd) for target in targets)
    if broad_recursive and (broad_targets or risky_target):
        return GuardFinding(
            risk="block",
            reason_code="broad_grep",
            reason="Context budget guard blocked broad grep output. Use -m, a scoped path, or a byte cap.",
            suggested_command="grep -RIn -m 50 '<pattern>' <scoped-path>",
        )
    return None


def _classify_log_stream(argv: list[str], command: str) -> GuardFinding | None:
    if not argv or _has_any_bound(command):
        return None
    executable = _executable_name(argv[0])
    if executable in {"docker", "kubectl"} and "logs" in argv[1:]:
        return GuardFinding(
            risk="block",
            reason_code="unbounded_logs",
            reason="Context budget guard blocked unbounded logs. Re-run with a byte cap or a small tail.",
            suggested_command=_safe_byte_cap_command(command),
        )
    if executable == "tail" and any(arg == "-f" or arg.startswith("-f") for arg in argv[1:]):
        return GuardFinding(
            risk="block",
            reason_code="streaming_tail",
            reason="Context budget guard blocked streaming tail output. Use a bounded tail or byte-capped command.",
            suggested_command=_safe_byte_cap_command(command.replace(" -f", "")),
        )
    return None


def _classify_structured_dump(argv: list[str], command: str) -> GuardFinding | None:
    if not argv or _has_any_bound(command):
        return None
    executable = _executable_name(argv[0])
    if executable == "jq" and len(argv) >= 3:
        return GuardFinding(
            risk="block",
            reason_code="unbounded_json_dump",
            reason="Context budget guard blocked a potentially large JSON dump. Use a targeted jq expression or byte cap.",
            suggested_command=_safe_byte_cap_command(command),
        )
    if executable in {"python", "python3"} and "json.tool" in argv:
        return GuardFinding(
            risk="block",
            reason_code="unbounded_json_dump",
            reason="Context budget guard blocked a potentially large JSON pretty-print. Use a targeted extractor or byte cap.",
            suggested_command=_safe_byte_cap_command(command),
        )
    return None


def _classify_python_script_output(argv: list[str], cwd: Path, command: str) -> GuardFinding | None:
    if not argv or _has_any_bound(command):
        return None
    executable = _executable_name(argv[0])
    if executable not in {"python", "python3"}:
        return None
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            index += 1
            break
        if arg in {"-c", "-m"}:
            return None
        if not arg.startswith("-"):
            break
        index += 1
    if index >= len(argv):
        return None
    script = argv[index]
    script_name = Path(script).name
    if _is_repo_validation_script(script, cwd) or _is_wakeup_script_path(script):
        return None
    script_parts = Path(script.replace("\\", "/")).parts
    if script_name in VALIDATION_SCRIPT_NAMES or script_name == "wakeup.py" or (script.endswith(".py") and "scripts" in script_parts):
        return GuardFinding(
            risk="block",
            reason_code="python_script_unbounded",
            reason="Context budget guard blocked an unbounded Python helper script. Redirect or cap output before putting it in the transcript.",
            suggested_command=_safe_byte_cap_command(command),
        )
    return None


def _classify_shell_script_output(argv: list[str], cwd: Path, command: str) -> GuardFinding | None:
    if not argv or _has_any_bound(command):
        return None
    executable = _executable_name(argv[0])
    if executable not in {"bash", "sh", "zsh"}:
        return None
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            index += 1
            break
        if not arg.startswith("-"):
            break
        index += 1
    if index >= len(argv):
        return None
    script = argv[index]
    if _is_repo_validation_script(script, cwd):
        return None
    script_name = Path(script).name
    script_parts = Path(script.replace("\\", "/")).parts
    if script_name in VALIDATION_SCRIPT_NAMES or (script.endswith(".sh") and "scripts" in script_parts):
        return GuardFinding(
            risk="block",
            reason_code="shell_script_unbounded",
            reason="Context budget guard blocked an unbounded shell helper script. Redirect or cap output before putting it in the transcript.",
            suggested_command=_safe_byte_cap_command(command),
        )
    return None


def _classify_python_full_read(command: str) -> GuardFinding | None:
    lowered = command.lower()
    if "print(open(" in lowered and ".read()" in lowered:
        return GuardFinding(
            risk="block",
            reason_code="python_print_full_file",
            reason="Context budget guard blocked a command that appears to print an entire file.",
        )
    return None


def classify_command(command: str, cwd: Path) -> GuardFinding | None:
    if not command.strip():
        return None
    if toxic_text_reasons(command):
        return GuardFinding(
            risk="block",
            reason_code="toxic_command_payload",
            reason="Context budget guard blocked a command containing inline base64, RED-sensitive, or oversized payload.",
        )
    for words in _shell_token_segments(command):
        tokens = _strip_environment_prefix(words)
        if not tokens:
            continue
        segment_command = shlex.join(words)
        bounded_command = _segment_bound_text(segment_command, command)
        if _is_validation_command(tokens, cwd):
            continue
        for classifier in (_classify_base64,):
            finding = classifier(tokens)
            if finding:
                return finding
        for classifier in (_classify_git_command,):
            finding = classifier(tokens, cwd, bounded_command)
            if finding:
                return finding
        for classifier in (_classify_display_command, _classify_rg_command):
            finding = classifier(tokens, cwd)
            if finding:
                return finding
        for classifier in (_classify_recursive_listing,):
            finding = classifier(tokens, cwd, bounded_command)
            if finding:
                return finding
        for classifier in (_classify_grep_command,):
            finding = classifier(tokens, cwd, bounded_command)
            if finding:
                return finding
        for classifier in (_classify_log_stream, _classify_structured_dump):
            finding = classifier(tokens, bounded_command)
            if finding:
                return finding
        finding = _classify_python_script_output(tokens, cwd, bounded_command)
        if finding:
            return finding
        finding = _classify_shell_script_output(tokens, cwd, bounded_command)
        if finding:
            return finding
        finding = _classify_python_full_read(segment_command)
        if finding:
            return finding
    return None


def payload_patch_text(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    if isinstance(tool_input, dict):
        for key in ("patch", "diff", "content"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
    if isinstance(tool_input, str):
        return tool_input
    return ""
