#!/usr/bin/env python3
"""Managed gateway for explicit, scoped Ralph user memories."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import subprocess
import sys
from pathlib import Path

from _memory_common import atomic_write_text, content_hash, normalize_classification, now_iso, ralph_home, render_frontmatter
from classify_learning import classify_learning


def safe_identifier(value: str) -> str:
    return value if value and all(char.isalnum() or char in "._-" for char in value) else ""


def git_value(workspace: Path, *args: str) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=workspace, text=True, capture_output=True, check=False, timeout=2)
    except OSError:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def context_for(workspace_root: str) -> tuple[str, str, str, str]:
    workspace = Path(workspace_root or os.getcwd()).expanduser().resolve()
    hooks_dir = Path(__file__).resolve().parents[2] / ".codex" / "hooks"
    if str(hooks_dir) not in sys.path:
        sys.path.insert(0, str(hooks_dir))
    try:
        from shared.active_context import active_context_from_payload  # type: ignore

        context = active_context_from_payload({"cwd": str(workspace), "session_id": os.environ.get("CODEX_SESSION_ID", "")})
        return context.project_slug, context.project_id, context.branch, context.sha
    except Exception:
        repo = git_value(workspace, "rev-parse", "--show-toplevel")
        if not repo:
            return "", "", "", ""
        root = Path(repo)
        return root.name, "", git_value(workspace, "branch", "--show-current"), git_value(workspace, "rev-parse", "--short", "HEAD")


def effective_classification(text: str, requested: str | None) -> str:
    computed = classify_learning(text)
    if not requested:
        return computed
    claimed = normalize_classification(requested)
    order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    return computed if order[computed] >= order[claimed] else claimed


def record_path(scope: str, memory_id: str, project_id: str) -> Path:
    root = ralph_home()
    if scope == "global":
        return root / "ledgers" / "user" / f"{memory_id}.md"
    return root / "projects" / project_id / "ledgers" / "user" / f"{memory_id}.md"


@contextlib.contextmanager
def record_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def receipt(status: str, memory_id: str, scope: str, classification: str = "", authoritative: bool = False) -> None:
    fields = [status, f"id={memory_id}", f"scope={scope}"]
    if classification:
        fields.append(f"classification={classification}")
    fields.append(f"authoritative={'true' if authoritative else 'false'}")
    print(" ".join(fields))


def remember(args: argparse.Namespace) -> int:
    text = args.text.strip()
    if not text:
        print("USER_MEMORY_REJECTED_EMPTY")
        return 2
    try:
        classification = effective_classification(text, args.classification)
    except Exception:
        print("USER_MEMORY_REJECTED_CLASSIFIER_FAILURE")
        return 3
    if classification == "RED":
        print("USER_MEMORY_REJECTED_RED")
        return 2
    repo, project_id, branch, commit = context_for(args.workspace_root)
    if args.scope == "repo" and (not repo or not project_id):
        print("USER_MEMORY_REJECTED_UNRESOLVED_REPO")
        return 2
    identity = project_id if args.scope == "repo" else "global"
    memory_id = "um-" + content_hash(f"{identity}\n{text}")[:24]
    path = record_path(args.scope, memory_id, project_id)
    with record_lock(path):
        if path.exists():
            receipt("USER_MEMORY_OK_UNCHANGED", memory_id, args.scope, classification, args.authoritative)
            return 0
        timestamp = now_iso()
        metadata = {
            "schema_version": "1", "memory_id": memory_id, "status": "active",
            "source": "explicit_user_memory", "user_authorized": "true",
            "authoritative": "true" if args.authoritative else "false", "scope": args.scope,
            "classification": classification, "source_fidelity": "direct_user_statement",
            "truth_status": "user_asserted_unverified", "repo": repo if args.scope == "repo" else "",
            "project_id": project_id if args.scope == "repo" else "", "branch": branch,
            "commit": commit, "session_id": os.environ.get("CODEX_SESSION_ID", ""),
            "content_hash": content_hash(text), "created_at": timestamp, "updated_at": timestamp,
        }
        atomic_write_text(path, render_frontmatter(metadata) + "\n\n" + text + "\n")
    receipt("USER_MEMORY_OK_CREATED", memory_id, args.scope, classification, args.authoritative)
    return 0


def forget(args: argparse.Namespace) -> int:
    memory_id = safe_identifier(args.memory_id)
    if not memory_id:
        print("USER_MEMORY_REJECTED_INVALID_ID")
        return 2
    _repo, project_id, _branch, _commit = context_for(args.workspace_root)
    if args.scope == "repo" and not project_id:
        print("USER_MEMORY_REJECTED_UNRESOLVED_REPO")
        return 2
    path = record_path(args.scope, memory_id, project_id)
    if not path.exists():
        print("USER_MEMORY_REJECTED_NOT_FOUND")
        return 2
    with record_lock(path):
        text = path.read_text(encoding="utf-8")
        if 'status: "deprecated"' in text:
            receipt("USER_MEMORY_OK_ALREADY_DEPRECATED", memory_id, args.scope)
            return 0
        if not text.startswith("---") or "\n---" not in text:
            print("USER_MEMORY_REJECTED_INVALID_RECORD")
            return 2
        header, body = text.split("\n---", 1)
        lines = [line for line in header.splitlines() if not line.startswith(("status:", "updated_at:", "deprecated_at:"))]
        timestamp = now_iso()
        lines.extend([f'status: "deprecated"', f'updated_at: "{timestamp}"', f'deprecated_at: "{timestamp}"'])
        atomic_write_text(path, "\n".join(lines) + "\n---" + body)
    receipt("USER_MEMORY_OK_DEPRECATED", memory_id, args.scope)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist or logically forget an explicit Ralph user memory.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    remember_parser = subparsers.add_parser("remember")
    remember_parser.add_argument("--text", required=True)
    remember_parser.add_argument("--scope", choices=("repo", "global"), default="repo")
    remember_parser.add_argument("--authoritative", action="store_true")
    remember_parser.add_argument("--classification")
    remember_parser.add_argument("--workspace-root", default=os.environ.get("RALPH_WORKSPACE_ROOT", ""))
    forget_parser = subparsers.add_parser("forget")
    forget_parser.add_argument("--id", dest="memory_id", required=True)
    forget_parser.add_argument("--scope", choices=("repo", "global"), default="repo")
    forget_parser.add_argument("--workspace-root", default=os.environ.get("RALPH_WORKSPACE_ROOT", ""))
    args = parser.parse_args()
    return remember(args) if args.command == "remember" else forget(args)


if __name__ == "__main__":
    raise SystemExit(main())
