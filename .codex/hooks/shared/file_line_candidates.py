from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any


PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update) File: (.+)$|^\*\*\* Move to: (.+)$", re.MULTILINE)
PATHISH_KEY_RE = re.compile(r"(?i)(^|_)(file|files|filename|path|paths|target|output)(_path|_file|$)")


def tool_input(payload: dict[str, Any]) -> Any:
    return payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}


def workspace_root(payload: dict[str, Any]) -> Path:
    data = tool_input(payload)
    candidates: list[str] = []
    if isinstance(payload.get("cwd"), str):
        candidates.append(payload["cwd"])
    if isinstance(data, dict):
        for key in ("cwd", "workdir", "working_directory"):
            value = data.get(key)
            if isinstance(value, str):
                candidates.append(value)
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists():
            return path.resolve()
    return Path.cwd().resolve()


def iter_pathish_values(value: Any, key_hint: bool = False) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            found.extend(iter_pathish_values(nested, key_hint or bool(PATHISH_KEY_RE.search(str(key)))))
    elif isinstance(value, list):
        for item in value:
            found.extend(iter_pathish_values(item, key_hint))
    elif isinstance(value, str) and key_hint:
        found.append(value)
    return found


def patch_paths(raw: Any) -> list[str]:
    if not isinstance(raw, str):
        return []
    paths: list[str] = []
    for match in PATCH_FILE_RE.finditer(raw):
        paths.append((match.group(1) or match.group(2) or "").strip())
    return paths


def patch_paths_from_value(value: Any) -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for nested in value.values():
            paths.extend(patch_paths_from_value(nested))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for item in value:
            paths.extend(patch_paths_from_value(item))
        return paths
    return patch_paths(value)


def normalize_path(raw: str, root: Path) -> Path | None:
    value = raw.strip().strip("`'\"")
    if not value or "\n" in value or len(value) > 500:
        return None
    if value.startswith(("http://", "https://", "app://", "plugin://")):
        return None
    line_suffix = re.match(r"^(.+):\d+(?::\d+)?$", value)
    if line_suffix:
        value = line_suffix.group(1)
    if value.startswith(("a/", "b/")):
        value = value[2:]

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve()
    except OSError:
        return None


def candidate_paths(payload: dict[str, Any]) -> set[Path]:
    data = tool_input(payload)
    root = workspace_root(payload)
    raw_paths = iter_pathish_values(data)
    raw_paths.extend(patch_paths_from_value(data))
    for key in ("file_path", "path"):
        value = payload.get(key)
        if isinstance(value, str):
            raw_paths.append(value)

    paths: set[Path] = set()
    for raw in raw_paths:
        path = normalize_path(raw, root)
        if path is not None:
            paths.add(path)
    return paths


def changed_git_paths(root: Path) -> set[Path]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=root,
            text=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return set()
    if result.returncode != 0 or not result.stdout:
        return set()

    entries = result.stdout.split(b"\0")
    paths: set[Path] = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        text = entry.decode("utf-8", errors="replace")
        if len(text) < 4:
            continue
        status = text[:2]
        if "D" not in status:
            path = normalize_path(text[3:], root)
            if path is not None:
                paths.add(path)
        if status[0] in {"R", "C"} and index < len(entries):
            path = normalize_path(entries[index].decode("utf-8", errors="replace"), root)
            index += 1
            if path is not None:
                paths.add(path)
    return paths


def git_stop_scan_enabled() -> bool:
    value = os.environ.get("RALPH_FILE_LINE_GUARD_SCAN_GIT", "")
    return value.lower() in {"1", "true", "yes", "on"}


def scan_paths(payload: dict[str, Any], event: str) -> set[Path]:
    root = workspace_root(payload)
    if event == "Stop" and git_stop_scan_enabled():
        return changed_git_paths(root)
    return candidate_paths(payload)
