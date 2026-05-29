#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from shared.file_line_candidates import candidate_paths, workspace_root
from shared.file_line_policy import SENSITIVE_PATH_RE
from shared.paths import append_jsonl, ensure_runtime, now_iso, read_hook_input, write_json


MAX_FRONTMATTER_BYTES = 4096
MAX_FRONTMATTER_LINES = 40


def is_markdown(path: Path) -> bool:
    return path.suffix.lower() in {".md", ".markdown"}


def frontmatter_has_shaping_true(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_FRONTMATTER_BYTES)
    except OSError:
        return False
    if b"\0" in raw:
        return False

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()[:MAX_FRONTMATTER_LINES]
    if not lines or lines[0].strip() != "---":
        return False

    found = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return found
        if stripped.lower() == "shaping: true":
            found = True
    return False


def shaping_paths(payload: dict) -> list[Path]:
    root = workspace_root(payload)
    found: list[Path] = []
    for path in sorted(candidate_paths(payload)):
        if path.is_symlink() or not path.is_file() or not is_markdown(path):
            continue
        if SENSITIVE_PATH_RE.search(path.as_posix()):
            continue
        if frontmatter_has_shaping_true(path):
            try:
                found.append(path.resolve().relative_to(root))
            except ValueError:
                found.append(path.resolve())
    return found


def record_warning(paths: list[Path], reason: str) -> None:
    try:
        root = ensure_runtime()
        append_jsonl(
            root / "reports" / "shaping-ripple-warnings.jsonl",
            {
                "created_at": now_iso(),
                "event": "shaping_ripple",
                "severity": "warn",
                "reason": reason,
                "files": [{"path": str(path)} for path in paths[:8]],
            },
        )
    except Exception:
        return


def main() -> int:
    payload = read_hook_input()
    paths = shaping_paths(payload)
    if not paths:
        return 0

    reason = (
        "Shaping ripple check: a Markdown file has shaping: true frontmatter. "
        "Verify related shaping artifacts stayed in sync: update affordance tables before Mermaid, "
        "reflect requirements changes in fit checks plus gaps/open questions, reflect shape-part changes "
        "in gaps/open questions by part, and sync work streams or slice plans with their related diagrams."
    )
    if os.environ.get("RALPH_SHAPING_RIPPLE_STRICT", "").lower() in {"1", "true", "yes", "on"}:
        write_json({"decision": "block", "reason": reason, "files": [{"path": str(path)} for path in paths[:8]]})
        return 0

    record_warning(paths, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
