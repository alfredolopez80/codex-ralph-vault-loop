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
        for classifier in (_classify_base64,):
            finding = classifier(tokens)
            if finding:
                return finding
        for classifier in (_classify_display_command, _classify_rg_command):
            finding = classifier(tokens, cwd)
            if finding:
                return finding
    return _classify_python_full_read(command)


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
