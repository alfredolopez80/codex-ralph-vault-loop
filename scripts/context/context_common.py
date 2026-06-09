from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_DIR = REPO_ROOT / "scripts" / "security"
if str(SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(SECURITY_DIR))

from sensitive_content import redact_text as redact_sensitive_text  # noqa: E402


SKIP_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ralph-codex",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
SKIP_PART_SEQUENCES = {
    (".codex", "sessions"),
    (".codex", "state"),
    (".codex", "logs"),
    ("vault", "raw"),
    ("vault", "inbox"),
}
BINARY_SUFFIXES = {
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
TEXT_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
DEFAULT_TAIL_BYTES = 1_000_000
TIMESTAMP_RE = re.compile(
    r"(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)


def is_binary_like(path: Path) -> bool:
    return path.suffix.lower() in BINARY_SUFFIXES


def should_skip(path: Path) -> bool:
    parts = path.parts
    if any(part in SKIP_DIRS for part in parts) or is_binary_like(path):
        return True
    return any(
        tuple(parts[index : index + len(sequence)]) == sequence
        for sequence in SKIP_PART_SEQUENCES
        for index in range(len(parts) - len(sequence) + 1)
    )


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def iter_repo_files(root: Path, *, max_files: int, max_depth: int) -> list[Path]:
    files: list[Path] = []
    root = root.resolve()
    for current, dir_names, file_names in os.walk(root):
        current_path = Path(current)
        rel_parts = current_path.relative_to(root).parts if current_path != root else ()
        dir_names[:] = sorted(
            name
            for name in dir_names
            if name not in SKIP_DIRS and len(rel_parts) < max_depth and not is_binary_like(current_path / name)
        )
        for name in sorted(file_names):
            if len(files) >= max_files:
                return files
            path = current_path / name
            if should_skip(path):
                continue
            depth = len(path.relative_to(root).parts) - 1
            if depth > max_depth:
                continue
            files.append(path)
    return files


def read_text_bounded(path: Path, max_bytes: int = DEFAULT_TAIL_BYTES) -> tuple[str, bool]:
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace"), truncated


def read_tail_text(path: Path, max_bytes: int = DEFAULT_TAIL_BYTES) -> tuple[str, bool]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            data = handle.read()
            return data.decode("utf-8", errors="replace"), True
        return handle.read().decode("utf-8", errors="replace"), False


def redact(value: object) -> str:
    redacted, _changed = redact_sensitive_text("" if value is None else str(value))
    return redacted


def preview(value: object, limit: int = 240) -> str:
    text = " ".join(redact(value).split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "...[truncated]"


def safe_key(value: object, limit: int = 120) -> str:
    return preview(value, limit=limit)


def redact_structure(value: Any, *, limit: int = 240) -> Any:
    if isinstance(value, dict):
        return {safe_key(key): redact_structure(item, limit=limit) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [redact_structure(item, limit=limit) for item in value]
    if isinstance(value, str):
        return preview(value, limit=limit)
    return value


def write_output(text: str, output: str | None) -> None:
    if output:
        path = Path(output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    print(text)


def write_json(data: Any, output: str | None) -> None:
    write_output(json.dumps(redact_structure(data), indent=2, sort_keys=True) + "\n", output)


def markdown_list(items: Iterable[str]) -> str:
    values = list(items)
    if not values:
        return "- none"
    return "\n".join(f"- `{item}`" for item in values)


def parse_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value)
    match = TIMESTAMP_RE.search(text)
    if not match:
        return None
    stamp = match.group("stamp").replace(" ", "T")
    if stamp.endswith("Z"):
        stamp = stamp[:-1] + "+00:00"
    if re.search(r"[+-]\d{4}$", stamp):
        stamp = stamp[:-2] + ":" + stamp[-2:]
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def compact_json_loads(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
