#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _memory_common import LAYER_FILES, compact_words, ensure_runtime, project_runtime_root, ralph_home, read_text


MAX_WAKEUP_WORDS = 1_500
CHECKPOINT_WAKEUP_WORDS = 500
HANDOFF_TTL_HOURS = 24
HANDOFF_FUTURE_SKEW_MINUTES = 5

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / ".codex" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from shared.checkpoint_io import (  # noqa: E402
    CheckpointError,
    checkpoint_is_injectable,
    checkpoint_paths,
    content_hash,
    load_latest,
    render_checkpoint,
)
from shared.active_context import active_context_from_payload  # noqa: E402
from shared.paths import now_iso  # noqa: E402
from shared.redaction import is_red, redact_text  # noqa: E402


def build_context(project_id: str = "", workspace_root: str = "", project: str = "") -> str:
    root = ensure_runtime(project_runtime_root(project_id) if project_id else None)
    global_root = ensure_runtime(ralph_home()) if project_id else root
    active_context = wakeup_active_context(project_id=project_id, workspace_root=workspace_root, project=project)
    sections = ["# Ralph Codex Wakeup", ""]
    for layer, filename in LAYER_FILES.items():
        layer_root = global_root if project_id and layer in {"L0", "L1"} else root
        text = read_text(layer_root / "layers" / filename, limit_chars=2_500).strip()
        sections.extend([f"## {layer}", text or "No content.", ""])
    handoff, handoff_budget = render_handoff_for_wakeup(root, project_id=project_id, workspace_root=workspace_root)
    if handoff:
        sections.extend(["## Latest Handoff", handoff_budget, "", handoff, ""])
    checkpoint = render_checkpoint_for_session(root, max_words=CHECKPOINT_WAKEUP_WORDS, context=active_context)
    if checkpoint:
        sections.extend(["## Latest Rolling Checkpoint", checkpoint, ""])
    return compact_words("\n".join(sections).strip() + "\n", MAX_WAKEUP_WORDS)


def wakeup_active_context(project_id: str = "", workspace_root: str = "", project: str = ""):
    if not project_id or not workspace_root:
        return None
    context = active_context_from_payload({"cwd": workspace_root, "session_id": current_session_id()})
    return replace(context, project_id=project_id, project_slug=project or context.project_slug)


def render_handoff_for_wakeup(root: Path, max_context_words: int = MAX_WAKEUP_WORDS, project_id: str = "", workspace_root: str = "") -> tuple[str, str]:
    path = root / "handoffs" / "latest.md"
    if not path.exists():
        return "", ""
    raw = read_text(path).strip()
    if not raw or is_red(raw):
        return "", ""
    metadata, body = parse_frontmatter(raw)
    if not handoff_is_injectable(metadata, body, project_id=project_id, workspace_root=workspace_root):
        return "", ""
    rendered = redact_text(body).strip()
    if not rendered or is_red(rendered):
        return "", ""
    session_id = current_session_id()
    handoff_hash = content_hash(rendered)
    if session_id and already_injected(root, session_id, handoff_hash, key="last_handoff_hash"):
        return "", ""

    word_count = len(rendered.split())
    budget, ratio = reinjection_policy(max_context_words)
    ratio_label = f"{ratio:.0%}"
    if word_count <= budget:
        if session_id:
            record_injection(root, session_id, handoff_hash, key="last_handoff_hash")
        return rendered, f"Handoff reinjection: full within {ratio_label} budget ({word_count}/{budget} words)."
    compacted = compact_words(rendered, budget).strip()
    if session_id:
        record_injection(root, session_id, handoff_hash, key="last_handoff_hash")
    return compacted, f"Handoff reinjection: compacted over {ratio_label} budget ({word_count}/{budget} words)."


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    metadata: dict[str, str] = {}
    end_index = -1
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value.strip("\"'")
        metadata[key] = str(parsed)
    if end_index < 0:
        return {}, text
    return metadata, "\n".join(lines[end_index + 1 :]).strip()


def handoff_is_injectable(metadata: dict[str, str], body: str, project_id: str = "", workspace_root: str = "") -> bool:
    if not body.strip() or is_red(body):
        return False
    classification = metadata.get("classification", "").upper()
    if project_id and classification not in {"GREEN", "YELLOW"}:
        return False
    if classification == "RED":
        return False
    if project_id:
        if metadata.get("project_id") != project_id:
            return False
        session_id = current_session_id()
        if session_id and metadata.get("session_id") != session_id:
            return False
        expected_workspace = workspace_instance_id(workspace_root)
        if not expected_workspace or metadata.get("workspace_instance_id") != expected_workspace:
            return False
    created_at = metadata.get("created_at", "")
    if project_id and not created_at:
        return False
    if created_at and handoff_is_stale(created_at):
        return False
    return True


def workspace_instance_id(workspace_root: str) -> str:
    if not workspace_root:
        return ""
    path = Path(workspace_root).expanduser()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]


def handoff_is_stale(created_at: str) -> bool:
    parsed = parse_time(created_at)
    if parsed is None:
        return True
    now = datetime.now(timezone.utc)
    if parsed - now > timedelta(minutes=HANDOFF_FUTURE_SKEW_MINUTES):
        return True
    ttl_hours = env_int("RALPH_HANDOFF_TTL_HOURS", HANDOFF_TTL_HOURS)
    ttl_hours = max(1, ttl_hours)
    return now - parsed > timedelta(hours=ttl_hours)


def parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def reinjection_budget(max_context_words: int = MAX_WAKEUP_WORDS) -> int:
    return reinjection_policy(max_context_words)[0]


def reinjection_policy(max_context_words: int = MAX_WAKEUP_WORDS) -> tuple[int, float]:
    ratio = env_float("RALPH_REINJECT_MAX_CONTEXT_RATIO", 0.15)
    ratio = min(max(ratio, 0.01), 0.50)
    hard_limit = env_int("RALPH_REINJECT_HARD_WORD_LIMIT", 700)
    hard_limit = max(1, hard_limit)
    return max(1, min(int(max_context_words * ratio), hard_limit)), ratio


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


def render_checkpoint_for_session(root: Path, max_words: int, context=None) -> str:
    try:
        checkpoint = load_latest(root)
    except CheckpointError:
        return ""
    if not checkpoint or not checkpoint_is_injectable(checkpoint, context):
        return ""
    session_id = current_session_id()
    checkpoint_session = str(checkpoint.get("session_id") or "").strip()
    if checkpoint_session and session_id and checkpoint_session != session_id:
        return ""
    checkpoint_hash = str(checkpoint.get("content_hash") or "")
    rendered = render_checkpoint(checkpoint, max_words=max_words).strip()
    if not checkpoint_hash:
        checkpoint_hash = content_hash(rendered)
    if session_id and already_injected(root, session_id, checkpoint_hash):
        return ""
    if session_id:
        record_injection(root, session_id, checkpoint_hash)
    return rendered


def current_session_id() -> str:
    value = os.environ.get("CODEX_SESSION_ID") or os.environ.get("RALPH_SESSION_ID") or ""
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return safe.strip("_")[:80]


def read_injection_state(root: Path) -> dict[str, Any]:
    path = checkpoint_paths(root)["injection_state"]
    if not path.exists():
        return {"sessions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sessions": {}}
    return data if isinstance(data, dict) else {"sessions": {}}


def already_injected(root: Path, session_id: str, checkpoint_hash: str, key: str = "last_hash") -> bool:
    sessions = read_injection_state(root).get("sessions", {})
    state = sessions.get(session_id, {}) if isinstance(sessions, dict) else {}
    return isinstance(state, dict) and state.get(key) == checkpoint_hash


def record_injection(root: Path, session_id: str, checkpoint_hash: str, key: str = "last_hash") -> None:
    path = checkpoint_paths(root)["injection_state"]
    path.parent.mkdir(parents=True, exist_ok=True)
    data = read_injection_state(root)
    sessions = data.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        data["sessions"] = sessions
    state = sessions.get(session_id, {}) if isinstance(sessions.get(session_id, {}), dict) else {}
    state[key] = checkpoint_hash
    if key == "last_hash":
        state["injected_at"] = now_iso()
    else:
        state[f"{key}_injected_at"] = now_iso()
    sessions[session_id] = state
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Print compact Ralph Codex wakeup context.")
    parser.add_argument("--project", default=os.environ.get("VAULT_PROJECT", ""))
    parser.add_argument("--project-id", default=os.environ.get("RALPH_PROJECT_ID", ""))
    parser.add_argument("--workspace-root", default=os.environ.get("RALPH_WORKSPACE_ROOT", ""))
    args = parser.parse_args()
    print(build_context(project_id=args.project_id, workspace_root=args.workspace_root, project=args.project), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
