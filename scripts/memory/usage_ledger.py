#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from memory_node import contains_red_material, sha256_text  # noqa: E402
from tree_store import TreeStore, ensure_within, fsync_dir  # noqa: E402

SCHEMA_VERSION = "ralph_memory_usage_v1"
SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def query_hash(query: object) -> str:
    normalized = " ".join(str(query or "").split())
    return sha256_text(normalized)


def safe_bool(value: object) -> bool:
    return bool(value) if isinstance(value, bool) else str(value).strip().lower() in {"1", "true", "yes", "on"}


def safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def safe_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if contains_red_material(text) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", text):
        return "id_hash_" + sha256_text(text)[:16]
    return text


def safe_reasons(items: object) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    if not isinstance(items, list):
        return output
    for item in items:
        if not isinstance(item, dict):
            continue
        output.append({"id": safe_id(item.get("node_id") or item.get("id")), "reason": safe_id(item.get("reason"))})
    return output


def safe_scope_hash(value: object) -> str:
    text = str(value or "").strip()
    return sha256_text(text) if text else ""


def reason_counts(rejections: list[dict[str, str]]) -> dict[str, int]:
    return dict(sorted(Counter(item["reason"] for item in rejections if item.get("reason")).items()))


def build_event(
    *,
    query: object,
    project_id: str,
    branch: str = "",
    session_id: str = "",
    engine: str = "tree",
    selected_memory_ids: object = None,
    rejected: object = None,
    fallback_used: object = False,
    shadow_enabled: object = False,
    raw_recommended: object = False,
    raw_opened: object = False,
    raw_included: object = False,
    token_budget_used: object = 0,
    token_budget_limit: object = 0,
    latency_ms: object = 0,
    ts: str | None = None,
) -> dict[str, Any]:
    selected = [safe_id(item) for item in selected_memory_ids] if isinstance(selected_memory_ids, list) else []
    selected = [item for item in selected if item]
    safe_rejected = safe_reasons(rejected)
    return {
        "schema_version": SCHEMA_VERSION,
        "ts": ts or now_iso(),
        "session_id": safe_id(session_id),
        "engine": safe_id(engine) or "tree",
        "query_hash": query_hash(query),
        "selected_memory_ids": selected,
        "selected_count": len(selected),
        "rejected_count": len(safe_rejected),
        "rejected_reason_counts": reason_counts(safe_rejected),
        "fallback_used": safe_bool(fallback_used),
        "shadow_enabled": safe_bool(shadow_enabled),
        "raw_recommended": safe_bool(raw_recommended),
        "raw_opened": safe_bool(raw_opened),
        "raw_included": False,
        "token_budget_used": safe_int(token_budget_used),
        "token_budget_limit": safe_int(token_budget_limit),
        "latency_ms": safe_int(latency_ms),
        "project_id_hash": safe_scope_hash(project_id),
        "branch_hash": safe_scope_hash(branch),
    }


def usage_path(ralph_home: Path, project_id: str) -> Path:
    store = TreeStore(ralph_home)
    root = store.ensure_layout(project_id)
    return ensure_within(root, root / "usage.jsonl")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_within(path.parent, path)
    if path.is_symlink():
        raise OSError("usage ledger path must not be a symlink")
    line = json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    fsync_dir(path.parent)


def write_event(ralph_home: Path, project_id: str, event: dict[str, Any]) -> bool:
    try:
        append_jsonl(usage_path(ralph_home, project_id), event)
        return True
    except Exception:
        return False


def record_usage(ralph_home: Path, project_id: str, **kwargs: Any) -> bool:
    try:
        event = build_event(project_id=project_id, **kwargs)
        return write_event(ralph_home, project_id, event)
    except Exception:
        return False


def iter_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION:
            events.append(payload)
    return events


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    rejected = Counter()
    for event in events:
        rejected.update(event.get("rejected_reason_counts", {}))
    return {
        "schema_version": "ralph_memory_usage_summary_v1",
        "event_count": len(events),
        "engine_counts": dict(sorted(Counter(str(event.get("engine", "")) for event in events).items())),
        "shadow_count": sum(1 for event in events if event.get("shadow_enabled") is True),
        "fallback_count": sum(1 for event in events if event.get("fallback_used") is True),
        "raw_recommended_count": sum(1 for event in events if event.get("raw_recommended") is True),
        "raw_opened_count": sum(1 for event in events if event.get("raw_opened") is True),
        "raw_included_count": sum(1 for event in events if event.get("raw_included") is True),
        "selected_total": sum(safe_int(event.get("selected_count")) for event in events),
        "rejected_total": sum(safe_int(event.get("rejected_count")) for event in events),
        "rejected_reason_counts": dict(sorted(rejected.items())),
    }


def resolve_context(project_root: Path, project_id: str = "") -> tuple[str, str]:
    if project_id:
        return project_id, ""
    try:
        from recall_v2 import context_for  # type: ignore

        context = context_for(project_root)
        return context.project_id, context.branch
    except Exception:
        return "p-" + sha256_text(str(project_root.expanduser().resolve()))[:16], ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect privacy-safe Ralph Memory Tree usage ledger.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--project-id", default="")
    parser.add_argument("--ralph-home", default=os.environ.get("RALPH_HOME", "~/.ralph-codex"))
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--tail", type=int, default=0)
    args = parser.parse_args()

    project_id, _branch = resolve_context(Path(args.project_root), args.project_id)
    path = usage_path(Path(args.ralph_home).expanduser(), project_id)
    events = iter_events(path)
    if args.tail:
        payload: Any = events[-max(0, args.tail) :]
    else:
        payload = summarize(events)
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
