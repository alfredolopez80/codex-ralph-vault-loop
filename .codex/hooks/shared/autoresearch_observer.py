from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .active_context import ActiveContext, active_context_from_payload
from .paths import now_iso, ralph_home
from .redaction import is_red, safe_preview


METRIC_RE = re.compile(r"^\s*METRIC\s+([A-Za-z_][A-Za-z0-9_.-]*)=([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$")
SAFE_PROJECT_ID_RE = re.compile(r"^p-[a-f0-9]{16}$")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
DEFAULT_MAX_BYTES = 65_536


class AutoResearchObserverError(RuntimeError):
    pass


def observer_enabled() -> bool:
    return os.environ.get("RALPH_AUTORESEARCH_OBSERVER", "1") != "0"


def max_bytes() -> int:
    raw = os.environ.get("RALPH_AUTORESEARCH_OBSERVER_MAX_BYTES")
    if not raw:
        return DEFAULT_MAX_BYTES
    try:
        return max(1_024, min(int(raw), 1_048_576))
    except ValueError:
        return DEFAULT_MAX_BYTES


def output_text_from_payload(payload: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("output", "output_preview", "outputPreview", "result", "stdout", "stderr"):
        value = payload.get(key)
        if isinstance(value, str):
            values.append(value)
    return "\n".join(values)


def command_from_payload(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input") or {}
    candidates = [payload.get("command"), payload.get("cmd")]
    if isinstance(tool_input, dict):
        candidates.extend([tool_input.get("command"), tool_input.get("cmd")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return safe_preview(candidate, 300)
    return safe_preview(str(payload.get("tool_name") or payload.get("tool") or ""), 120)


def parse_metrics(text: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for line in text.splitlines():
        match = METRIC_RE.match(line)
        if match:
            metrics[match.group(1)] = float(match.group(2))
    return metrics


def read_active_config(cwd: Path) -> dict[str, Any] | None:
    if not (cwd / "autoresearch.md").is_file():
        return None
    ledger = cwd / "autoresearch.jsonl"
    if not ledger.is_file():
        return None
    with ledger.open("r", encoding="utf-8", errors="replace") as handle:
        for _ in range(20):
            line = handle.readline()
            if not line:
                break
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                return None
            if isinstance(entry, dict) and entry.get("entry_type") == "config":
                if entry.get("observer_enabled") is False:
                    return None
                return entry
    return None


def safe_project_autoresearch_root(base: Path, project_id: str) -> Path:
    if not SAFE_PROJECT_ID_RE.fullmatch(project_id):
        raise AutoResearchObserverError("unsafe project id")
    if base.is_symlink():
        raise AutoResearchObserverError("runtime root is a symlink")
    projects_path = base / "projects"
    if projects_path.is_symlink():
        raise AutoResearchObserverError("projects runtime path is a symlink")
    root = projects_path.resolve(strict=False)
    raw_project_root = root / project_id
    if raw_project_root.is_symlink():
        raise AutoResearchObserverError("project runtime path is a symlink")
    project_root = raw_project_root.resolve(strict=False)
    try:
        project_root.relative_to(root)
    except ValueError as exc:
        raise AutoResearchObserverError("project path escapes runtime root") from exc
    autoresearch_root = project_root / "autoresearch"
    if autoresearch_root.is_symlink():
        raise AutoResearchObserverError("autoresearch runtime path is a symlink")
    autoresearch_resolved = autoresearch_root.resolve(strict=False)
    try:
        autoresearch_resolved.relative_to(project_root)
    except ValueError as exc:
        raise AutoResearchObserverError("autoresearch path escapes project root") from exc
    return autoresearch_root


def safe_observation_path(root: Path, filename: str) -> Path:
    if not SAFE_FILENAME_RE.fullmatch(filename) or filename in {".", ".."}:
        raise AutoResearchObserverError("unsafe observation filename")
    if root.is_symlink():
        raise AutoResearchObserverError("observation root is a symlink")
    path = root / filename
    resolved_root = root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise AutoResearchObserverError("observation path escapes autoresearch root") from exc
    if path.is_symlink():
        raise AutoResearchObserverError("observation file is a symlink")
    return path


def append_atomic_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    if is_red(data):
        raise AutoResearchObserverError("pending observation is RED-sensitive")
    write_flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        write_flags |= os.O_NOFOLLOW
    fd = os.open(path, write_flags, 0o600)
    try:
        os.write(fd, (data + "\n").encode("utf-8"))
    finally:
        os.close(fd)
        try:
            path.chmod(0o600)
        except OSError:
            pass


def active_cwd(payload: dict[str, Any], context: ActiveContext) -> Path:
    tool_input = payload.get("tool_input") or {}
    for source in (payload, tool_input if isinstance(tool_input, dict) else {}):
        for key in ("cwd", "workdir", "working_directory", "workspace_root"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                path = Path(value).expanduser()
                if path.exists():
                    return path.resolve()
    return context.workspace_root


def observe_post_tool_payload(payload: dict[str, Any], context: ActiveContext | None = None) -> dict[str, Any] | None:
    if not observer_enabled():
        return None
    context = context or active_context_from_payload(payload)
    cwd = active_cwd(payload, context)
    config = read_active_config(cwd)
    if not config:
        return None
    text = output_text_from_payload(payload)
    if not text:
        return None
    preview_bytes = text.encode("utf-8", errors="replace")[: max_bytes()]
    preview = preview_bytes.decode("utf-8", errors="replace")
    if is_red(preview):
        return {"observed": False, "reason": "red_output"}
    metrics = parse_metrics(preview)
    if not metrics:
        return None
    runtime_root = safe_project_autoresearch_root(ralph_home(), context.project_id)
    path = safe_observation_path(runtime_root, "pending-metrics.jsonl")
    event = {
        "created_at": now_iso(),
        "event": "autoresearch_metric_observed",
        "project_id": context.project_id,
        "project": context.project_slug,
        "session_id": context.session_id,
        "workspace_instance_id": context.workspace_instance_id,
        "branch": context.branch,
        "sha": context.sha,
        "cwd": str(cwd),
        "segment_id": config.get("segment_id", ""),
        "metric_names": sorted(metrics),
        "metrics": metrics,
        "command": command_from_payload(payload),
        "success": bool(payload.get("success")) if isinstance(payload.get("success"), bool) else None,
        "preview_sha256": hashlib.sha256(preview.encode("utf-8")).hexdigest(),
        "preview_bytes": len(preview_bytes),
    }
    append_atomic_jsonl(path, event)
    return {"observed": True, "path": str(path), "metric_names": sorted(metrics)}


def safe_observe_post_tool_payload(payload: dict[str, Any], context: ActiveContext | None = None) -> dict[str, Any] | None:
    try:
        return observe_post_tool_payload(payload, context)
    except Exception:
        return None
