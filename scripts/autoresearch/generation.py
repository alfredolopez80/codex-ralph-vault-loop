from __future__ import annotations

import json
import os
import re
import tempfile
import hashlib
from pathlib import Path
from typing import Any

from common import AutoResearchError, assert_not_red, now_iso


SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
DEFAULT_PREVIEW_BYTES = 65_536
REQUIRED_TEXT_ARTIFACTS = {
    "candidate_patch": "candidate.patch",
    "stdout_preview": "benchmark.stdout.preview.txt",
    "stderr_preview": "benchmark.stderr.preview.txt",
    "improvement": "improvement.md",
}
REQUIRED_JSON_ARTIFACTS = {
    "manifest": "manifest.json",
    "command": "command.json",
    "metrics": "metrics.json",
    "checks": "checks.json",
    "hard_gates": "hard_gates.json",
    "decision": "decision.json",
    "asi": "asi.json",
    "trace": "trace.json",
}


def safe_id(label: str, value: str) -> str:
    if not SAFE_ID_RE.fullmatch(value):
        raise AutoResearchError(f"unsafe {label}: {value!r}")
    if value in {".", ".."} or value.startswith("."):
        raise AutoResearchError(f"unsafe {label}: {value!r}")
    return value


def safe_preview(value: str, limit: int = DEFAULT_PREVIEW_BYTES) -> str:
    encoded = value.encode("utf-8", errors="replace")[:limit]
    text = encoded.decode("utf-8", errors="replace")
    assert_not_red("generation preview", text)
    return text


def ensure_child(root: Path, child: Path) -> Path:
    resolved_root = root.resolve()
    resolved_child = child.resolve(strict=False)
    try:
        resolved_child.relative_to(resolved_root)
    except ValueError as exc:
        raise AutoResearchError(f"path escapes generation root: {child}") from exc
    return child


def reject_symlink_ancestors(root: Path, child: Path) -> None:
    current = root
    if current.exists() and current.is_symlink():
        raise AutoResearchError(f"generation root is a symlink: {root}")
    try:
        relative_parts = child.relative_to(root).parts
    except ValueError as exc:
        raise AutoResearchError(f"path escapes generation root: {child}") from exc
    for part in relative_parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise AutoResearchError(f"generation path component is a symlink: {current}")


def artifact_record(path: Path, text: str) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": len(text.encode("utf-8")),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "scanner": "sensitive_content.is_red",
        "scan_status": "pass",
    }


def atomic_write_text(path: Path, text: str) -> dict[str, Any]:
    assert_not_red(str(path.name), text)
    reject_symlink_ancestors(path.parents[2] if path.parent.name.startswith("gen_") else path.parent, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return artifact_record(path, text)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return atomic_write_text(path, text)


def generation_dir(cwd: Path, segment_id: str, generation_id: str) -> Path:
    safe_segment = safe_id("segment_id", segment_id)
    safe_generation = safe_id("generation_id", generation_id)
    root = cwd / "autoresearch.runs"
    path = root / safe_segment / safe_generation
    reject_symlink_ancestors(root, path)
    return ensure_child(root, path)


def next_generation_id(cwd: Path, segment_id: str) -> str:
    segment = cwd / "autoresearch.runs" / safe_id("segment_id", segment_id)
    if not segment.exists():
        return "gen_000"
    existing = sorted(path.name for path in segment.iterdir() if path.is_dir() and re.fullmatch(r"gen_\d{3}", path.name))
    if not existing:
        return "gen_000"
    return f"gen_{int(existing[-1].split('_', 1)[1]) + 1:03d}"


def write_generation_bundle(cwd: Path, segment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    generation_id = payload.get("generation_id") or next_generation_id(cwd, segment_id)
    target = generation_dir(cwd, segment_id, str(generation_id))
    target.mkdir(parents=True, exist_ok=True)
    for directory in (cwd / "autoresearch.runs", target.parent, target):
        try:
            directory.chmod(0o700)
        except OSError:
            pass

    files: dict[str, str] = {}
    scan_records: dict[str, dict[str, Any]] = {}
    manifest = {
        "created_at": now_iso(),
        "segment_id": segment_id,
        "generation_id": generation_id,
        "schema": "ralph-autoresearch-generation-v1",
    }
    scan_records["manifest"] = atomic_write_json(target / "manifest.json", manifest)
    files["manifest"] = str(target / "manifest.json")

    text_files = {
        "candidate_patch": ("candidate.patch", payload.get("candidate_patch", "")),
        "stdout_preview": ("benchmark.stdout.preview.txt", safe_preview(str(payload.get("stdout", "")))),
        "stderr_preview": ("benchmark.stderr.preview.txt", safe_preview(str(payload.get("stderr", "")))),
        "improvement": ("improvement.md", payload.get("improvement", "Pending synthesis.\n")),
    }
    for key, (name, content) in text_files.items():
        scan_records[key] = atomic_write_text(target / name, str(content))
        files[key] = str(target / name)

    json_files = {
        "command": ("command.json", payload.get("command", {})),
        "metrics": ("metrics.json", payload.get("metrics", {})),
        "checks": ("checks.json", payload.get("checks", {})),
        "hard_gates": ("hard_gates.json", payload.get("hard_gates", {})),
        "decision": ("decision.json", payload.get("decision", {})),
        "asi": ("asi.json", payload.get("asi", {})),
        "trace": ("trace.json", payload.get("trace", {})),
    }
    for key, (name, content) in json_files.items():
        if not isinstance(content, dict):
            raise AutoResearchError(f"generation {name} must be an object")
        scan_records[key] = atomic_write_json(target / name, content)
        files[key] = str(target / name)

    expected = set(REQUIRED_TEXT_ARTIFACTS) | set(REQUIRED_JSON_ARTIFACTS)
    missing = sorted(expected - set(scan_records))
    if missing:
        raise AutoResearchError(f"generation artifacts were not scanned: {', '.join(missing)}")
    scan_report = {
        "created_at": now_iso(),
        "scanner": "sensitive_content.is_red",
        "fail_closed": True,
        "required_artifacts": sorted(expected),
        "scanned_artifacts": scan_records,
    }
    scan_records["scan_report"] = atomic_write_json(target / "scan_report.json", scan_report)
    files["scan_report"] = str(target / "scan_report.json")

    return {"generation_id": str(generation_id), "path": str(target), "files": files}
