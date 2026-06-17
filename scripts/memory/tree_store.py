from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .memory_node import (
        MemoryNode,
        MemoryNodeValidationError,
        contains_red_material,
        deterministic_node_id,
        sha256_text,
        validate_node,
    )
else:  # pragma: no cover - script-style import support.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from memory_node import (  # type: ignore
        MemoryNode,
        MemoryNodeValidationError,
        contains_red_material,
        deterministic_node_id,
        sha256_text,
        validate_node,
    )


class TreeStoreError(ValueError):
    pass


class TreeStorePathError(TreeStoreError):
    pass

SHA256_RE = re.compile(r"[a-f0-9]{64}")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_ralph_home() -> Path:
    """Codex runtime root for NON-tree state (handoffs, ledgers, checkpoints).

    Intentionally unchanged: ``~/.ralph-codex``. The shared MEMORY TREE root is
    resolved separately by ``default_memory_home`` so unifying the tree with the
    claude agent (Wave 5) does NOT move codex's session/handoff state.
    """
    return Path("~/.ralph-codex").expanduser()


def default_memory_home() -> Path:
    """Root for the SHARED durable memory tree (Wave 5, Addendum 3, 2026-06-17).

    Honors ``RALPH_MEMORY_HOME`` (default ``~/.ralph``) so codex and claude
    converge on ONE shared memory tree root. This affects ONLY the memory tree;
    ``default_ralph_home`` (handoffs/ledgers) stays ``~/.ralph-codex``.
    """
    home = os.environ.get("RALPH_MEMORY_HOME", "").strip()
    return Path(home or "~/.ralph").expanduser()


# ---------------------------------------------------------------------------
# Canonical project id derivation -- byte-identical to the claude agent's
# multi-agent-ralph-loop/scripts/memory/tree_store.py (Wave 5, Addendum 3).
# Ported verbatim so the SAME target repo yields the SAME project_id from
# either agent. Override via RALPH_PROJECT_ID (codex compatibility).
# ---------------------------------------------------------------------------

def _git_remote_url(repo_root: Path) -> str:
    """Best-effort git remote URL for *repo_root*; '' if none / not a repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def resolve_main_repo_root(repo_root: Path) -> Path:
    """Return the MAIN repository root for *repo_root*, unwrapping worktrees.

    Single source of truth for "which project does this path belong to". For a
    normal checkout this is ``git rev-parse --show-toplevel``. For a linked
    worktree the top-level ``.git`` is a *file* pointing at
    ``<main>/.git/worktrees/<name>``; the main repo root is three levels up from
    that gitdir. Outside a git repo (or on any git error) the resolved input
    path is returned verbatim as a stable fallback.
    """
    start = repo_root.expanduser().resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return start
    if result.returncode != 0:
        return start
    toplevel = Path(result.stdout.strip())
    git_marker = toplevel / ".git"
    if not git_marker.is_file():
        # Normal checkout: .git is a directory, toplevel IS the main repo.
        return toplevel
    try:
        content = git_marker.read_text(encoding="utf-8").strip()
    except OSError:
        return toplevel
    gitdir = content.split("gitdir:", 1)[-1].strip()
    gitdir_path = (
        Path(gitdir) if Path(gitdir).is_absolute() else (toplevel / gitdir).resolve()
    )
    # .git/worktrees/<name> -> up 3 levels to the main repo root.
    if "worktrees" in gitdir_path.parts:
        return gitdir_path.parent.parent.parent
    return toplevel


def repo_remote_hash(repo_root: Path) -> str:
    """Stable 16-char hash of the main repo's remote URL (path as fallback)."""
    main_repo = resolve_main_repo_root(repo_root)
    remote = _git_remote_url(main_repo)
    material = remote or str(main_repo)
    return sha256_text(material)[:16]


def workspace_instance_id(repo_root: Path) -> str:
    """Identity of the PROJECT: the main-repo directory name (worktree-unwrapped)."""
    return safe_segment(resolve_main_repo_root(repo_root).name, "workspace_instance_id")


def compute_project_id(repo_root: Path) -> str:
    """Canonical project id: main-repo remote-hash + main-repo dir name.

    Worktrees are unwrapped to their main repository first, so two worktrees of
    the same repo resolve to the SAME project id. ``RALPH_PROJECT_ID`` override
    wins when set (codex compatibility). When unset, the git-remote-hash
    derivation matches the claude agent byte-for-byte.
    """
    override = os.environ.get("RALPH_PROJECT_ID", "").strip()
    if override:
        return safe_segment(override, "project_id")
    main_repo = resolve_main_repo_root(repo_root)
    return safe_segment(
        f"{repo_remote_hash(main_repo)}_{workspace_instance_id(main_repo)}",
        "project_id",
    )


def safe_segment(value: object, label: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text or text.startswith("/") or "\\" in text or "/" in text or ".." in text:
        raise TreeStorePathError(f"{label} is not a safe path segment")
    return text


def ensure_within(base: Path, candidate: Path) -> Path:
    base_resolved = base.resolve(strict=False)
    candidate_resolved = candidate.resolve(strict=False)
    if candidate_resolved != base_resolved and base_resolved not in candidate_resolved.parents:
        raise TreeStorePathError(f"path escapes memory tree root: {candidate}")
    return candidate


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_within(path.parent, path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        fsync_dir(path.parent)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n")


class TreeStore:
    def __init__(self, ralph_home: Path | None = None) -> None:
        # Default to the SHARED memory home (Wave 5) so codex writes to the same
        # tree the claude agent reads. Explicit ``ralph_home`` still wins (tests
        # pass tmp_path; callers may override).
        self.ralph_home = (ralph_home or default_memory_home()).expanduser()

    def projects_root(self) -> Path:
        return self.ralph_home / "memory_tree" / "projects"

    def project_tree(self, project_id: str) -> Path:
        # Layout aligned with the claude agent (Wave 5, Addendum 3):
        #   {RALPH_MEMORY_HOME}/memory_tree/projects/{project_id}/
        # (was {home}/projects/{project_id}/memory_tree/ -- inverted nesting).
        safe_project = safe_segment(project_id, "project_id")
        root = self.projects_root() / safe_project
        return ensure_within(self.projects_root(), root)

    def nodes_dir(self, project_id: str) -> Path:
        return self.project_tree(project_id) / "nodes"

    def raw_dir(self, project_id: str) -> Path:
        return self.project_tree(project_id) / "raw"

    def snapshots_dir(self, project_id: str) -> Path:
        return self.project_tree(project_id) / "snapshots"

    def node_path(self, project_id: str, node_id: str) -> Path:
        safe_node = safe_segment(node_id, "node_id")
        path = self.nodes_dir(project_id) / f"{safe_node}.json"
        return ensure_within(self.project_tree(project_id), path)

    def raw_path(self, project_id: str, digest: str) -> Path:
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise TreeStorePathError("raw digest must be a sha256 hex digest")
        path = self.raw_dir(project_id) / f"{digest}.txt"
        return ensure_within(self.project_tree(project_id), path)

    def ensure_layout(self, project_id: str) -> Path:
        root = self.project_tree(project_id)
        for directory in (root / "nodes", root / "raw", root / "snapshots"):
            directory.mkdir(parents=True, exist_ok=True)
            ensure_within(root, directory)
        for filename, default in (
            ("usage.jsonl", ""),
            ("links.jsonl", ""),
            ("index.json", "{}\n"),
        ):
            path = root / filename
            ensure_within(root, path)
            if not path.exists():
                atomic_write_text(path, default)
        return root

    def create_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        node = MemoryNode.from_dict(payload)
        if self.node_exists(node.project_id, node.node_id):
            raise TreeStoreError(f"node already exists: {node.node_id}")
        return self._write_node(node)

    def update_node(self, project_id: str, node_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.load_node(project_id, node_id)
        if current is None:
            raise TreeStoreError(f"node not found: {node_id}")
        merged = {**current, **updates, "node_id": current["node_id"], "project_id": current["project_id"], "updated_at": now_iso()}
        node = MemoryNode.from_dict(merged)
        return self._write_node(node)

    def _write_node(self, node: MemoryNode) -> dict[str, Any]:
        node = validate_node(node)
        root = self.ensure_layout(node.project_id)
        path = self.node_path(node.project_id, node.node_id)
        payload = node.to_dict()
        atomic_write_json(path, payload)
        self._write_index(node.project_id)
        self._append_usage(root, {"event": "node_written", "node_id": node.node_id, "created_at": now_iso()})
        return payload

    def load_node(self, project_id: str, node_id: str) -> dict[str, Any] | None:
        path = self.node_path(project_id, node_id)
        if not path.exists():
            return None
        ensure_within(self.nodes_dir(project_id), path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return MemoryNode.from_dict(payload).to_dict()
        except MemoryNodeValidationError:
            return None

    def list_nodes(self, project_id: str) -> list[dict[str, Any]]:
        directory = self.nodes_dir(project_id)
        if not directory.exists():
            return []
        nodes: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                ensure_within(directory, path)
            except TreeStorePathError:
                continue
            node = self.load_node(project_id, path.stem)
            if node is not None:
                nodes.append(node)
        return nodes

    def node_exists(self, project_id: str, node_id: str) -> bool:
        return self.load_node(project_id, node_id) is not None

    def save_raw(self, project_id: str, content: str, sensitivity: str = "YELLOW", safe: bool = True) -> dict[str, str]:
        if sensitivity not in {"GREEN", "YELLOW"}:
            raise MemoryNodeValidationError("raw sensitivity must be GREEN or YELLOW")
        if not safe or contains_red_material(content):
            raise MemoryNodeValidationError("raw content is unsafe")
        self.ensure_layout(project_id)
        digest = sha256_text(content)
        path = self.raw_path(project_id, digest)
        atomic_write_text(path, content)
        return {"sha256": digest, "path": str(path), "sensitivity": sensitivity}

    def read_raw(self, project_id: str, digest: str) -> str | None:
        path = self.raw_path(project_id, digest)
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None
        return None if contains_red_material(content) else content

    def find_by_hash(self, project_id: str, digest: str) -> dict[str, Any]:
        raw_exists = self.raw_path(project_id, digest).exists()
        node_ids: list[str] = []
        for node in self.list_nodes(project_id):
            node_hash = sha256_text(json.dumps(node, ensure_ascii=True, sort_keys=True))
            raw_ref = node.get("raw_ref") if isinstance(node.get("raw_ref"), dict) else {}
            if node_hash == digest or raw_ref.get("sha256") == digest:
                node_ids.append(str(node["node_id"]))
        return {"raw_exists": raw_exists, "node_ids": sorted(node_ids)}

    def snapshot_tree(self, project_id: str, snapshot_id: str | None = None) -> str:
        root = self.ensure_layout(project_id)
        snapshots = self.snapshots_dir(project_id)
        snapshots.mkdir(parents=True, exist_ok=True)
        snapshot_name = safe_segment(snapshot_id or f"snapshot_{now_iso().replace(':', '').replace('+', 'Z')}", "snapshot_id")
        final = ensure_within(snapshots, snapshots / snapshot_name)
        if final.exists():
            raise TreeStoreError(f"snapshot already exists: {snapshot_name}")
        temp = snapshots / f".{snapshot_name}.tmp"
        if temp.exists():
            shutil.rmtree(temp)
        temp.mkdir(parents=True)
        try:
            for name in ("nodes", "raw"):
                source = root / name
                target = temp / name
                if source.exists():
                    self._reject_symlink_tree(source)
                    shutil.copytree(source, target, symlinks=False)
                else:
                    target.mkdir()
            for name in ("index.json", "usage.jsonl", "links.jsonl"):
                source = root / name
                if source.exists():
                    shutil.copy2(source, temp / name)
            atomic_write_json(
                temp / "manifest.json",
                {"created_at": now_iso(), "project_id": project_id, "snapshot_id": snapshot_name},
            )
            os.replace(temp, final)
            fsync_dir(snapshots)
        finally:
            if temp.exists():
                shutil.rmtree(temp)
        return snapshot_name

    @staticmethod
    def _reject_symlink_tree(root: Path) -> None:
        if root.is_symlink():
            raise TreeStoreError("memory tree snapshot source contains a symlink")
        for item in root.rglob("*"):
            if item.is_symlink():
                raise TreeStoreError("memory tree snapshot source contains a symlink")

    def restore_snapshot(self, project_id: str, snapshot_id: str) -> None:
        root = self.ensure_layout(project_id)
        snapshot = ensure_within(self.snapshots_dir(project_id), self.snapshots_dir(project_id) / safe_segment(snapshot_id, "snapshot_id"))
        if not snapshot.exists() or not snapshot.is_dir():
            raise TreeStoreError(f"snapshot not found: {snapshot_id}")
        manifest = snapshot / "manifest.json"
        try:
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TreeStoreError("snapshot manifest is invalid") from exc
        if manifest_payload.get("project_id") != project_id:
            raise TreeStoreError("snapshot project_id mismatch")
        self._validate_snapshot(project_id, snapshot)
        for name in ("nodes", "raw"):
            source_dir = snapshot / name
            target_dir = root / name
            target_dir.mkdir(parents=True, exist_ok=True)
            for existing in target_dir.glob("*"):
                if existing.is_file() or existing.is_symlink():
                    existing.unlink()
            if source_dir.exists():
                for source_file in sorted(source_dir.glob("*")):
                    if source_file.is_file() and not source_file.is_symlink():
                        atomic_write_text(target_dir / source_file.name, source_file.read_text(encoding="utf-8"))
        for name in ("index.json", "usage.jsonl", "links.jsonl"):
            source = snapshot / name
            if source.exists() and source.is_file() and not source.is_symlink():
                atomic_write_text(root / name, source.read_text(encoding="utf-8"))
        self._write_index(project_id)

    def _validate_snapshot(self, project_id: str, snapshot: Path) -> None:
        for node_file in sorted((snapshot / "nodes").glob("*.json")):
            if node_file.is_symlink():
                raise TreeStoreError("snapshot contains a symlinked node")
            try:
                node_payload = json.loads(node_file.read_text(encoding="utf-8"))
                node = MemoryNode.from_dict(node_payload)
            except (OSError, json.JSONDecodeError, MemoryNodeValidationError) as exc:
                raise TreeStoreError(f"snapshot node is invalid: {node_file.name}") from exc
            if node.project_id != project_id:
                raise TreeStoreError("snapshot node project_id mismatch")
        for raw_file in sorted((snapshot / "raw").glob("*.txt")):
            if raw_file.is_symlink():
                raise TreeStoreError("snapshot contains a symlinked raw file")
            try:
                content = raw_file.read_text(encoding="utf-8")
            except OSError as exc:
                raise TreeStoreError(f"snapshot raw file is unreadable: {raw_file.name}") from exc
            if contains_red_material(content):
                raise TreeStoreError("snapshot raw file is unsafe")

    def _write_index(self, project_id: str) -> None:
        root = self.ensure_layout(project_id)
        nodes = self.list_nodes(project_id)
        index = {
            "schema_version": "ralph_memory_tree_index_v1",
            "project_id": project_id,
            "updated_at": now_iso(),
            "nodes": [
                {
                    "node_id": node["node_id"],
                    "memory_type": node.get("memory_type", ""),
                    "branch": node.get("branch", ""), "created_on_branch": node.get("created_on_branch", node.get("branch", "")),
                    "visibility": node.get("visibility", "branch_local"), "promotion_status": node.get("promotion_status", "not_promoted"),
                    "summary": node.get("summary", ""),
                    "trigger": node.get("trigger", {}),
                    "topic_tags": node.get("topic_tags", []),
                    "source_paths": node.get("source_paths", []),
                    "links": node.get("links", []), "quality": node.get("quality", {}),
                }
                for node in nodes
            ],
        }
        atomic_write_json(root / "index.json", index)

    def _append_usage(self, root: Path, event: dict[str, Any]) -> None:
        path = root / "usage.jsonl"
        line = json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        atomic_write_text(path, existing + line)
