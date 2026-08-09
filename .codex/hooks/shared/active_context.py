from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import REPO_ROOT, ralph_home

PROJECT_ID_PREFIX = "p"


@dataclass(frozen=True)
class ActiveContext:
    ralph_code_root: Path
    workspace_root: Path
    git_root: Path | None
    durable_root: Path | None
    project_slug: str
    project_id: str
    remote_url_hash: str
    branch: str
    sha: str
    session_id: str
    workspace_instance_id: str


def tool_input(payload: dict[str, Any]) -> Any:
    return payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}


def active_context_from_payload(payload: dict[str, Any] | None = None, *, resolve_git: bool = True) -> ActiveContext:
    payload = payload or {}
    workspace = workspace_root(payload)
    git_root, branch, sha = git_metadata_for(workspace, use_subprocess=resolve_git)
    identity_root = git_root or workspace
    remote_url = (
        git_value(identity_root, "config", "--get", "remote.origin.url")
        if git_root and resolve_git
        else fast_remote_url(identity_root) if git_root else ""
    )
    branch = str(payload.get("branch") or payload.get("git_branch") or branch).strip()
    sha = str(payload.get("sha") or payload.get("git_sha") or sha).strip()
    project_slug = safe_slug(remote_repo_name(remote_url) or identity_root.name)
    workspace_instance_id = hash_text(str(workspace.resolve()))[:16]
    return ActiveContext(
        ralph_code_root=REPO_ROOT.resolve(),
        workspace_root=workspace,
        git_root=git_root,
        durable_root=None,
        project_slug=project_slug,
        project_id=project_id_for(identity_root, remote_url),
        remote_url_hash=hash_text(remote_url)[:16] if remote_url else "",
        branch=branch,
        sha=sha,
        session_id=safe_session_id(payload),
        workspace_instance_id=workspace_instance_id,
    )


def workspace_root(payload: dict[str, Any]) -> Path:
    candidates: list[str] = []
    for key in ("cwd", "workdir", "working_directory", "workspace_root"):
        value = payload.get(key)
        if isinstance(value, str):
            candidates.append(value)
    data = tool_input(payload)
    if isinstance(data, dict):
        for key in ("cwd", "workdir", "working_directory", "workspace_root"):
            value = data.get(key)
            if isinstance(value, str):
                candidates.append(value)
    env_pwd = os.environ.get("PWD")
    if env_pwd:
        candidates.append(env_pwd)

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists():
            return path.resolve()
    return Path.cwd().resolve()


def git_root_for(path: Path) -> Path | None:
    result = run_git(path, "rev-parse", "--show-toplevel")
    if not result:
        return None
    git_root = Path(result).expanduser()
    return git_root.resolve() if git_root.exists() else None


def git_metadata_for(path: Path, *, use_subprocess: bool = True) -> tuple[Path | None, str, str]:
    if not use_subprocess:
        return fast_git_metadata_for(path)
    result = run_git(path, "rev-parse", "--show-toplevel", "--abbrev-ref", "HEAD")
    if not result:
        return git_root_for(path), "", ""
    lines = result.splitlines()
    if len(lines) < 2:
        return git_root_for(path), "", ""
    git_root = Path(lines[0]).expanduser()
    if not git_root.exists():
        return None, "", ""
    return git_root.resolve(), lines[1].strip(), git_value(git_root, "rev-parse", "--short", "HEAD")


def _git_dir_for(path: Path) -> tuple[Path | None, Path | None]:
    """Resolve a worktree's git metadata without spawning a process."""
    candidate = path.resolve()
    for parent in (candidate, *candidate.parents):
        marker = parent / ".git"
        if marker.is_dir():
            return parent, marker
        if marker.is_file():
            try:
                line = marker.read_text(encoding="utf-8", errors="replace").splitlines()[0]
                if line.lower().startswith("gitdir:"):
                    raw = line.split(":", 1)[1].strip()
                    git_dir = Path(raw).expanduser()
                    if not git_dir.is_absolute():
                        git_dir = (marker.parent / git_dir).resolve()
                    return parent, git_dir
            except (OSError, IndexError):
                return parent, None
    return None, None


def _read_ref(git_dir: Path, ref: str) -> str:
    directories = [git_dir]
    common = _common_git_dir(git_dir)
    if common != git_dir:
        directories.append(common)
    for directory in directories:
        try:
            value = (directory / ref).read_text(encoding="ascii", errors="ignore").strip()
        except OSError:
            value = ""
        if value:
            return value
        packed = directory / "packed-refs"
        try:
            for line in packed.read_text(encoding="ascii", errors="ignore").splitlines():
                if line and not line.startswith("#") and " " in line:
                    sha, packed_ref = line.split(" ", 1)
                    if packed_ref == ref:
                        return sha.strip()
        except OSError:
            continue
    return ""


def _common_git_dir(git_dir: Path) -> Path:
    marker = git_dir / "commondir"
    try:
        raw = marker.read_text(encoding="ascii", errors="ignore").strip()
    except OSError:
        return git_dir
    if not raw:
        return git_dir
    common = Path(raw)
    return (git_dir / common).resolve() if not common.is_absolute() else common.resolve()


def fast_git_metadata_for(path: Path) -> tuple[Path | None, str, str]:
    git_root, git_dir = _git_dir_for(path)
    if git_root is None or git_dir is None:
        return None, "", ""
    try:
        head = (git_dir / "HEAD").read_text(encoding="ascii", errors="ignore").strip()
    except OSError:
        return git_root, "", ""
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        branch = ref.removeprefix("refs/heads/")
        sha = _read_ref(git_dir, ref)
    else:
        branch = "HEAD"
        sha = head
    return git_root, branch, sha[:12]


def fast_remote_url(root: Path) -> str:
    """Read only remote.origin.url from local git config, without git CLI."""
    git_root, git_dir = _git_dir_for(root)
    config_root = _common_git_dir(git_dir) if git_dir else (git_root / ".git" if git_root else Path(""))
    config_path = config_root / "config"
    try:
        lines = config_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    in_origin = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped.lower() in {'[remote "origin"]', "[remote.origin]"}
            continue
        if in_origin and stripped.lower().startswith("url") and "=" in stripped:
            return stripped.split("=", 1)[1].strip()
    return ""


def git_value(root: Path, *args: str) -> str:
    return run_git(root, *args)


def run_git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def project_id_for(identity_root: Path, remote_url: str = "") -> str:
    root = identity_root.resolve()
    if remote_url:
        material = f"remote:{remote_url}|name:{remote_repo_name(remote_url) or root.name}|workspace:{root}"
    else:
        material = f"path:{root}"
    return f"{PROJECT_ID_PREFIX}-{hash_text(material)[:16]}"


def remote_repo_name(remote_url: str) -> str:
    tail = remote_url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return tail.removesuffix(".git")


def project_runtime_root(context: ActiveContext, root: Path | None = None) -> Path:
    return (root or ralph_home()) / "projects" / context.project_id


def legacy_runtime_root(root: Path | None = None) -> Path:
    return root or ralph_home()


def ensure_project_runtime(context: ActiveContext, root: Path | None = None) -> Path:
    base = project_runtime_root(context, root)
    for relative in ("layers", "ledgers", "handoffs", "reports", "cost", "checkpoints"):
        (base / relative).mkdir(parents=True, exist_ok=True)
    metadata_path = base / "project.json"
    metadata = project_metadata_json(context)
    if metadata_path.is_symlink():
        raise OSError("refusing symlink project metadata")
    try:
        unchanged = metadata_path.read_text(encoding="utf-8") == metadata
    except FileNotFoundError:
        unchanged = False
    except OSError:
        # Preserve the existing write attempt for unreadable or malformed
        # metadata; the caller's established fail-open boundary handles it.
        unchanged = False
    if not unchanged:
        metadata_path.write_text(metadata, encoding="utf-8")
    return base


def project_metadata(context: ActiveContext) -> dict[str, str]:
    return {
        "project_id": context.project_id,
        "project_slug": context.project_slug,
        "workspace_root": str(context.workspace_root),
        "git_root": str(context.git_root or ""),
        "remote_url_hash": context.remote_url_hash,
        "branch": context.branch,
        "sha": context.sha,
        "session_id": context.session_id,
        "workspace_instance_id": context.workspace_instance_id,
        "ralph_code_root": str(context.ralph_code_root),
    }


def project_metadata_json(context: ActiveContext) -> str:
    import json

    return json.dumps(project_metadata(context), indent=2, sort_keys=True) + "\n"


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or "default"


def safe_session_id(payload: dict[str, Any]) -> str:
    value = (
        payload.get("session_id")
        or payload.get("sessionId")
        or os.environ.get("CODEX_SESSION_ID")
        or os.environ.get("RALPH_SESSION_ID")
        or "unknown"
    )
    text = "".join(char if char.isalnum() or char in "._-" else "_" for char in str(value))
    return text.strip("_")[:80] or "unknown"


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
