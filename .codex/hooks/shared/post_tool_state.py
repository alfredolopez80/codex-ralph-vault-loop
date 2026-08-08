"""Small, project-scoped state helpers for the consolidated PostToolUse hook.

The state contains only digests and bounded metrics.  It deliberately lives
under ``RALPH_HOME`` (the approved Ralph runtime), never in ``~/.codex`` or in
the repository, and treats every filesystem failure as an operational
fail-open condition.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX is the supported runtime.
    fcntl = None  # type: ignore[assignment]

from .active_context import ActiveContext
from .paths import ralph_home

STATE_VERSION = 1
DEFAULT_TTL_SECONDS = 60 * 60
DEFAULT_MAX_ENTRIES = 2_048
SAFE_PROJECT_ID_RE = re.compile(r"^p-[a-f0-9]{16}$")


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _ttl_seconds() -> int:
    try:
        return max(1, min(int(os.environ.get("RALPH_POST_TOOL_DEDUPE_TTL_SECONDS", DEFAULT_TTL_SECONDS)), 86_400))
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS


def _max_entries() -> int:
    try:
        return max(16, min(int(os.environ.get("RALPH_POST_TOOL_DEDUPE_MAX_ENTRIES", DEFAULT_MAX_ENTRIES)), 10_000))
    except (TypeError, ValueError):
        return DEFAULT_MAX_ENTRIES


def _path_has_symlink(path: Path) -> bool:
    candidate = Path(os.path.abspath(os.fspath(path)))
    for part in (candidate, *candidate.parents):
        if part.exists() and part.is_symlink():
            return True
        if part == part.parent:
            break
    return False


def state_root(context: ActiveContext) -> Path | None:
    """Return a bounded state directory, or ``None`` when it is unsafe."""
    if not SAFE_PROJECT_ID_RE.fullmatch(context.project_id):
        return None
    try:
        configured = ralph_home()
        if _path_has_symlink(configured):
            return None
        base = configured.resolve(strict=False)
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        projects = base / "projects"
        if projects.is_symlink():
            return None
        projects.mkdir(parents=True, exist_ok=True, mode=0o700)
        project = projects / context.project_id
        if project.is_symlink():
            return None
        project.mkdir(parents=True, exist_ok=True, mode=0o700)
        root = project / "post-tool"
        if root.is_symlink():
            return None
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        return root
    except OSError:
        return None


def _id_from_sources(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    sources: list[dict[str, Any]] = [payload]
    for name in ("tool_input", "toolInput", "input", "tool_response", "toolResponse"):
        value = payload.get(name)
        if isinstance(value, dict):
            sources.append(value)
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return "".join(char if char.isalnum() or char in "._:-" else "_" for char in str(value).strip())[:160]
    return ""


def original_tool_use_id(payload: dict[str, Any]) -> str:
    return _id_from_sources(
        payload,
        (
            "originating_tool_use_id",
            "originatingToolUseId",
            "parent_tool_use_id",
            "parentToolUseId",
            "original_tool_use_id",
            "originalToolUseId",
            "tool_use_id",
            "toolUseId",
            "tool_call_id",
            "toolCallId",
            "call_id",
            "callId",
        ),
    )


def turn_id(payload: dict[str, Any]) -> str:
    return _id_from_sources(payload, ("turn_id", "turnId", "conversation_turn_id", "conversationTurnId")) or "unknown"


def dedupe_key(context: ActiveContext, payload: dict[str, Any]) -> str | None:
    tool_use_id = original_tool_use_id(payload)
    if not tool_use_id:
        return None
    material = "\0".join(
        (
            "post-tool-dedupe-v1",
            context.project_id,
            context.workspace_instance_id,
            context.branch,
            context.sha,
            context.session_id,
            turn_id(payload),
            tool_use_id,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _safe_path(root: Path, name: str) -> Path | None:
    path = root / name
    try:
        if path.is_symlink() or path.resolve(strict=False).parent != root.resolve(strict=False):
            return None
    except OSError:
        return None
    return path


def _load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != STATE_VERSION:
            raise ValueError("incompatible state")
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError("invalid entries")
        return data
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        if path.exists() and not path.is_symlink():
            invalid = path.with_name(f"{path.name}.invalid.{int(time.time())}")
            with contextlib.suppress(OSError):
                os.replace(path, invalid)
        return {"schema_version": STATE_VERSION, "entries": []}


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    if path.is_symlink():
        raise OSError("state file is a symlink")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=True, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


@contextmanager
def dedupe_claim(context: ActiveContext, payload: dict[str, Any]) -> Iterator[tuple[bool, str | None]]:
    """Serialize one tool-use claim and commit it after component execution."""
    root = state_root(context)
    key = dedupe_key(context, payload)
    if root is None or key is None or fcntl is None:
        yield False, key
        return

    state_path = _safe_path(root, "dedupe.json")
    lock_path = _safe_path(root, "dedupe.lock")
    if state_path is None or lock_path is None:
        yield False, key
        return

    try:
        with lock_path.open("a+", encoding="utf-8") as lock:
            if lock_path.is_symlink():
                yield False, key
                return
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = _load_state(state_path)
            now = time.time()
            entries: dict[str, float] = {}
            for item in state.get("entries", []):
                if not isinstance(item, dict):
                    continue
                item_key = item.get("key")
                try:
                    seen_at = float(item.get("seen_at"))
                except (TypeError, ValueError):
                    continue
                if isinstance(item_key, str) and len(item_key) == 64 and now - seen_at <= _ttl_seconds():
                    entries[item_key] = seen_at
            duplicate = key in entries
            try:
                yield duplicate, key
                if not duplicate:
                    entries[key] = now
                if not duplicate:
                    ordered = sorted(entries.items(), key=lambda pair: pair[1], reverse=True)[: _max_entries()]
                    try:
                        _atomic_write(
                            state_path,
                            {
                                "schema_version": STATE_VERSION,
                                "updated_at": _now_iso(),
                                "entries": [{"key": item_key, "seen_at": seen_at} for item_key, seen_at in ordered],
                            },
                        )
                    except (OSError, ValueError, TypeError):
                        pass
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError, TypeError):
        # Operational dedupe state is advisory. A write/permission failure
        # must not stop the executor or turn a successful tool result into a
        # hook failure.
        yield False, key


def append_metric(context: ActiveContext, event: dict[str, Any]) -> bool:
    root = state_root(context)
    if root is None or fcntl is None:
        return False
    path = _safe_path(root, "metrics.jsonl")
    lock_path = _safe_path(root, "metrics.lock")
    if path is None or lock_path is None:
        return False
    payload = {"schema_version": STATE_VERSION, "created_at": _now_iso(), **event}
    try:
        with lock_path.open("a+", encoding="utf-8") as lock:
            if lock_path.is_symlink() or path.is_symlink():
                return False
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                os.write(fd, (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8"))
            finally:
                os.close(fd)
            with contextlib.suppress(OSError):
                path.chmod(0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return True
    except (OSError, TypeError, ValueError):
        return False


def directory_bytes(root: Path | None) -> int:
    if root is None or not root.exists() or root.is_symlink():
        return 0
    total = 0
    try:
        for item in root.rglob("*"):
            if item.is_symlink() or not item.is_file():
                continue
            total += item.stat().st_size
            if total > 16 * 1024 * 1024:
                return 16 * 1024 * 1024
    except OSError:
        return total
    return total
