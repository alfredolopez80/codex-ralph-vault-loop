from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
