from __future__ import annotations

import subprocess
from pathlib import Path

from safety import assert_safe_path


def run(args: list[str], cwd: Path, *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, input=input_text, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode != 0:
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr or result.stdout}")
    return result


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], repo, check=check).stdout


def repo_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd(), check=False)
    if result.returncode != 0:
        raise SystemExit("autoreview must run inside a git repository")
    return Path(result.stdout.strip()).resolve()


def current_branch(repo: Path) -> str:
    return git(repo, "branch", "--show-current", check=False).strip() or "detached"


def is_dirty(repo: Path) -> bool:
    return bool(git(repo, "status", "--porcelain").strip())


def choose_target(repo: Path, mode: str, base_ref: str | None) -> tuple[str, str | None]:
    branch = current_branch(repo)
    if mode == "local" or (mode == "auto" and is_dirty(repo)):
        return "local", None
    if mode == "commit":
        return "commit", None
    if mode == "branch" or (mode == "auto" and branch != "main"):
        return "branch", base_ref or "origin/main"
    raise SystemExit("no review target: clean main checkout and no forced mode")


def read_text(path: Path, limit: int = 60_000) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return f"[unreadable: {exc}]"
    if b"\0" in data:
        return "[binary file omitted]"
    text = data.decode("utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit] + f"\n\n[truncated at {limit} characters]\n"
    return text


def changed_paths(repo: Path, target: str, target_ref: str | None, commit_ref: str, *, include_untracked: bool) -> set[str]:
    if target == "local":
        sources = [git(repo, "diff", "--name-only", "--cached"), git(repo, "diff", "--name-only")]
        if include_untracked:
            sources.append(git(repo, "ls-files", "--others", "--exclude-standard"))
    elif target == "branch":
        if not target_ref:
            raise SystemExit("branch target requires a base ref")
        sources = [git(repo, "diff", "--name-only", f"{target_ref}...HEAD")]
    else:
        sources = [git(repo, "show", "--name-only", "--format=", commit_ref)]
    paths: set[str] = set()
    for source in sources:
        for line in source.splitlines():
            rel = line.strip()
            if rel:
                paths.add(rel)
    return paths


def local_bundle(repo: Path, *, include_untracked: bool) -> str:
    parts = [
        "# Git Status",
        git(repo, "status", "--short"),
        "# Staged Diff",
        git(repo, "diff", "--cached", "--stat"),
        git(repo, "diff", "--cached", "--patch", "--find-renames"),
        "# Unstaged Diff",
        git(repo, "diff", "--stat"),
        git(repo, "diff", "--patch", "--find-renames"),
    ]
    if include_untracked:
        untracked = [line for line in git(repo, "ls-files", "--others", "--exclude-standard").splitlines() if line]
        if untracked:
            parts.append("# Untracked Files")
            for rel in untracked:
                assert_safe_path(rel, context="untracked")
                parts.append(f"## {rel}\n{read_text(repo / rel)}")
    return "\n\n".join(parts)


def branch_bundle(repo: Path, base_ref: str, *, fetch: bool) -> str:
    if fetch:
        git(repo, "fetch", "origin", "--quiet", check=False)
    return "\n\n".join(
        [
            "# Branch Diff",
            f"base: {base_ref}",
            git(repo, "diff", "--stat", f"{base_ref}...HEAD"),
            git(repo, "diff", "--patch", "--find-renames", f"{base_ref}...HEAD"),
        ]
    )


def commit_bundle(repo: Path, commit_ref: str) -> str:
    return "\n\n".join(
        [
            "# Commit Diff",
            f"commit: {commit_ref}",
            git(repo, "show", "--stat", "--format=fuller", commit_ref),
            git(repo, "show", "--patch", "--find-renames", "--format=fuller", commit_ref),
        ]
    )


def load_extra_files(values: list[str] | None, *, label: str) -> str:
    chunks: list[str] = []
    for raw in values or []:
        assert_safe_path(raw, context=label)
        path = Path(raw)
        if path.is_dir():
            raise SystemExit(f"--{label} must be a file, got directory: {path}")
        chunks.append(f"# {label}: {path}\n{read_text(path)}")
    return "\n\n".join(chunks)
