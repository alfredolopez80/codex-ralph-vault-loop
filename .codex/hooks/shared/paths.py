from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from .persistence_metrics import WriteResult

DEFAULT_RALPH_HOME = Path("~/.ralph-codex").expanduser()


def repo_root() -> Path:
    override = os.environ.get("RALPH_REPO_ROOT")
    if override:
        return Path(override).expanduser()
    marker = Path(__file__).resolve().parents[1] / ".ralph-repo-root"
    if marker.exists():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            return Path(value).expanduser()
    return Path(__file__).resolve().parents[3]


REPO_ROOT = repo_root()


def ralph_home() -> Path:
    return Path(os.environ.get("RALPH_HOME", str(DEFAULT_RALPH_HOME))).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def ensure_runtime() -> Path:
    root = ralph_home()
    for relative in ("layers", "ledgers", "handoffs", "reports", "cost"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


def read_hook_input() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True))


def append_jsonl(path: Path, payload: dict[str, Any]) -> WriteResult:
    """Append one bounded JSON record and report its exact encoded size.

    Existing callers intentionally ignore the return value.  Returning a
    content-free result lets hot-path dispatchers account for writes without a
    recursive runtime scan while preserving the historical fail-open shape.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(encoded.decode("utf-8"))
        return WriteResult(changed=True, bytes_written=len(encoded), files_written=(path.name,), appends=1)
    except (OSError, TypeError, ValueError):
        return WriteResult.unknown()
