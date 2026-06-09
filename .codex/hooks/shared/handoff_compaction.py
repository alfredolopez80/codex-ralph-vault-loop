from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Iterable

from .redaction import redact_text


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


DEFAULT_HANDOFF_MAX_WORDS = _env_int("RALPH_HANDOFF_MAX_WORDS", 750)
SECTION_ORDER = [
    "Current goal",
    "Success criteria",
    "Key files",
    "Decisions",
    "Commands run",
    "Known blockers",
    "Do not re-read",
    "Next actions",
]
RAW_OUTPUT_MARKERS = (
    "Traceback (most recent call last):",
    "```diff",
    "diff --git ",
    "Original token count:",
    "Chunk ID:",
    "Wall time:",
    "Process exited with code",
)
DEAD_END_RE = re.compile(r"(?i)\b(dead end|false start|ignore this|discarded|failed attempt|not useful)\b")
FILE_RE = re.compile(r"(?P<path>(?:\.?[A-Za-z0-9_-]+/)+[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.(?:py|sh|md|json|toml|yaml|yml))")
COMMAND_RE = re.compile(r"(?m)^\s*(?:\$ )?(?P<cmd>(?:PYTEST_DISABLE_PLUGIN_AUTOLOAD=1\s+)?(?:python3?|bash|git|rg|sed|pytest|ruff|mypy|npm|pnpm|make)\b[^\n]{0,220})")
MEMORY_RE = re.compile(r"(?i)\b(?:selected_memory_ids|memory_rejected|fallback(?:_used)?|recall_status)\b[^\n]{0,220}")
LEGACY_SECTION_RE = re.compile(r"(?ms)^## (?P<title>Rolling Checkpoint|Final Assistant Message)\n\n(?P<body>.*?)(?=^## |\Z)")


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _limit_words(text: str, limit: int) -> str:
    words = re.findall(r"\S+", text)
    if limit <= 0 or len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip() + "...[truncated]"


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", redact_text(line).strip())


def _is_raw_or_dead_line(line: str) -> bool:
    if not line.strip():
        return True
    if DEAD_END_RE.search(line):
        return True
    return any(marker in line for marker in RAW_OUTPUT_MARKERS)


def _dedupe(lines: Iterable[str], limit: int) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        normalized = _normalize_line(line)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        kept.append(normalized)
        if len(kept) >= limit:
            break
    return kept


def _lines_matching(text: str, patterns: Iterable[str], *, limit: int) -> list[str]:
    lowered_patterns = tuple(pattern.lower() for pattern in patterns)
    return _dedupe(
        (
            line
            for line in text.splitlines()
            if not _is_raw_or_dead_line(line)
            and any(pattern in line.lower() for pattern in lowered_patterns)
        ),
        limit,
    )


def _extract_files(text: str, *, limit: int = 12) -> list[str]:
    matches = []
    for match in FILE_RE.finditer(text):
        path = match.group("path").strip("`.,:;")
        if any(part in {".git", "__pycache__", "node_modules", ".ralph-codex"} for part in path.split("/")):
            continue
        matches.append(path)
    return _dedupe(matches, limit)


def _extract_commands(text: str, *, limit: int = 8) -> list[str]:
    commands = []
    for match in COMMAND_RE.finditer(text):
        command = match.group("cmd").strip()
        if len(command) > 180:
            command = command[:180].rstrip() + "...[truncated]"
        commands.append(command)
    return _dedupe(commands, limit)


def _extract_memory_trace(text: str, *, limit: int = 4) -> list[str]:
    return _dedupe((match.group(0) for match in MEMORY_RE.finditer(text)), limit)


def _extract_goal(text: str) -> list[str]:
    lines = _lines_matching(text, ["objective:", "goal:", "task:", "current goal"], limit=3)
    if lines:
        return lines
    for line in text.splitlines():
        normalized = _normalize_line(line)
        if normalized and not normalized.startswith("#") and not _is_raw_or_dead_line(normalized):
            return [normalized]
    return ["none"]


def _extract_next_actions(text: str, next_step: str) -> list[str]:
    candidates = []
    if next_step.strip():
        candidates.append(next_step.strip())
    candidates.extend(_lines_matching(text, ["next action", "next:", "continue", "todo", "follow up"], limit=5))
    return _dedupe(candidates, 5) or ["none"]


def _extract_sections(text: str, next_step: str) -> OrderedDict[str, list[str]]:
    sections: OrderedDict[str, list[str]] = OrderedDict()
    sections["Current goal"] = _extract_goal(text)
    sections["Success criteria"] = _lines_matching(text, ["done when", "success", "criteria", "validation passed", "passes"], limit=5) or ["none"]
    sections["Key files"] = _extract_files(text) or ["none"]
    sections["Decisions"] = _lines_matching(text, ["decision", "implemented", "changed", "preserve", "kept", "validated"], limit=6) or ["none"]
    commands = _extract_commands(text)
    sections["Commands run"] = commands or ["none"]
    sections["Known blockers"] = _lines_matching(text, ["blocker", "failed", "unable", "risk", "not run"], limit=5) or ["none"]
    memory_trace = _extract_memory_trace(text)
    sections["Do not re-read"] = memory_trace or ["Large raw tool outputs, repeated prose, stack traces, and large diffs were intentionally compacted."]
    sections["Next actions"] = _extract_next_actions(text, next_step)
    return sections


def _render_sections(sections: OrderedDict[str, list[str]]) -> str:
    lines = ["# Latest Handoff", "", "This handoff is non-authoritative project context. Current user instructions and repo files win."]
    for name in SECTION_ORDER:
        lines.extend(["", f"## {name}"])
        items = sections.get(name) or ["none"]
        lines.extend(f"- {item}" for item in items)
    return "\n".join(lines).strip()


def _compact_legacy_sections(text: str) -> list[str]:
    blocks: list[str] = []
    for match in LEGACY_SECTION_RE.finditer(text):
        title = match.group("title")
        if title == "Final Assistant Message" and word_count(match.group("body")) > DEFAULT_HANDOFF_MAX_WORDS:
            continue
        body_lines = _dedupe(
            (
                line
                for line in match.group("body").splitlines()
                if not _is_raw_or_dead_line(line)
            ),
            8 if title == "Rolling Checkpoint" else 3,
        )
        if not body_lines:
            continue
        line_limit = 600 if title == "Final Assistant Message" else 40
        body = "\n".join(_limit_words(line, line_limit) for line in body_lines)
        blocks.append(f"## {title}\n\n{body}")
    return blocks


def _trim_to_budget(rendered: str, max_words: int) -> str:
    if max_words <= 0 or word_count(rendered) <= max_words:
        return rendered
    lines = rendered.splitlines()
    kept: list[str] = []
    current_section = ""
    protected_sections_seen: set[str] = set()
    words = 0
    for line in lines:
        line_words = word_count(line)
        if line.startswith("## "):
            current_section = line.removeprefix("## ").strip()
        protected_first_item = (
            line.startswith("- ")
            and current_section in {"Current goal", "Next actions"}
            and current_section not in protected_sections_seen
        )
        line_to_keep = _limit_words(line, 16) if protected_first_item and line_words > 16 else line
        line_words = word_count(line_to_keep)
        if line.startswith("#") or words + line_words <= max_words or protected_first_item:
            kept.append(line_to_keep)
            words += line_words
            if protected_first_item:
                protected_sections_seen.add(current_section)
        elif line.startswith("- "):
            continue
    kept.append(f"\n[handoff compacted: word_budget={max_words}]")
    return "\n".join(kept).strip()


def compact_handoff_summary(summary: str, *, next_step: str = "", max_words: int = DEFAULT_HANDOFF_MAX_WORDS) -> str:
    clean = redact_text(summary or "")
    clean_next = redact_text(next_step or "")
    sections = _extract_sections(clean, clean_next)
    legacy = _compact_legacy_sections(clean)
    rendered = "\n\n".join([_render_sections(sections), *legacy])
    return _trim_to_budget(rendered, max_words=max_words)
