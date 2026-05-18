from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import active_context_from_payload  # noqa: E402


def init_git(path: Path, remote: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.DEVNULL)
    if remote:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)


def test_active_context_uses_payload_cwd_git_root(tmp_path: Path) -> None:
    repo = tmp_path / "project-a"
    init_git(repo, "git@example.com:org/project-a.git")
    nested = repo / "nested"
    nested.mkdir()

    context = active_context_from_payload({"cwd": str(nested), "session_id": "abc"})

    assert context.workspace_root == nested.resolve()
    assert context.git_root == repo.resolve()
    assert context.project_slug == "project-a"
    assert context.session_id == "abc"
    assert context.project_id.startswith("p-")
    assert context.remote_url_hash


def test_active_context_uses_tool_workdir_and_stable_remote_identity(tmp_path: Path) -> None:
    repo_a = tmp_path / "worktree-a"
    repo_b = tmp_path / "worktree-b"
    remote = "git@example.com:org/shared.git"
    init_git(repo_a, remote)
    init_git(repo_b, remote)

    context_a = active_context_from_payload({"tool_input": {"workdir": str(repo_a)}})
    context_b = active_context_from_payload({"tool_input": {"workdir": str(repo_b)}})

    assert context_a.workspace_root == repo_a.resolve()
    assert context_b.workspace_root == repo_b.resolve()
    assert context_a.project_id == context_b.project_id
    assert context_a.workspace_instance_id != context_b.workspace_instance_id
