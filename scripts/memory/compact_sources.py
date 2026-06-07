from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


MAX_SOURCE_BYTES = 60_000
DEFAULT_VAULT_DIR = Path("~/Documents/Obsidian/MiVault").expanduser()
FORBIDDEN_PARTS = {"raw", "inbox"}


@dataclass(frozen=True)
class Source:
    path: Path
    relative_path: str
    kind: str


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def skip(path: Path, root: Path, reason: str, kind: str) -> dict[str, object]:
    return {"source_path": relative_to_root(path, root), "source_kind": kind, "reason": reason}


def skip_source(source: Source, reason: str) -> dict[str, object]:
    return {"source_path": source.relative_path, "source_kind": source.kind, "reason": reason}


def safe_files(base: Path, root: Path, kind: str) -> tuple[list[Path], list[dict[str, object]]]:
    files: list[Path] = []
    skipped: list[dict[str, object]] = []
    if base.is_symlink():
        return files, [skip(base, root, "symlink_source", kind)]
    for current, dirnames, filenames in os.walk(base, followlinks=False):
        current_path = Path(current)
        safe_dirs: list[str] = []
        for dirname in sorted(dirnames):
            child = current_path / dirname
            if child.is_symlink():
                skipped.append(skip(child, root, "symlink_source", kind))
            else:
                safe_dirs.append(dirname)
        dirnames[:] = safe_dirs
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                skipped.append(skip(path, root, "symlink_source", kind))
            elif path.is_file():
                files.append(path)
    return sorted(files), skipped


def vault_skip(path: Path, vault_root: Path, reason: str) -> dict[str, object]:
    return {"source_path": "vault/" + str(path.relative_to(vault_root)), "source_kind": "vault_curated", "reason": reason}


def curated_vault_dirs(vault_dir: Path, project_slug: str) -> list[Path]:
    return [
        vault_dir / "global" / "wiki",
        vault_dir / "global" / "decisions",
        vault_dir / "projects" / project_slug / "wiki",
        vault_dir / "projects" / project_slug / "decisions",
        vault_dir / "projects" / project_slug / "sessions",
        vault_dir / "projects" / project_slug / "handoffs",
    ]


def discover_sources(
    root: Path,
    max_items: int,
    vault_dir: Path | None = None,
    project_slug: str = "",
) -> tuple[list[Source], list[dict[str, object]]]:
    specs = (
        ("checkpoint", "checkpoints", (".json",)),
        ("handoff", "handoffs", (".md",)),
        ("ledger", "ledgers", (".md", ".json", ".jsonl")),
    )
    sources: list[Source] = []
    skipped: list[dict[str, object]] = []
    for name in sorted(FORBIDDEN_PARTS):
        base = root / name
        if base.exists():
            files, symlink_skips = safe_files(base, root, name)
            skipped.extend(symlink_skips)
            skipped.extend(skip(path, root, "forbidden_source", name) for path in files)
    for kind, dirname, suffixes in specs:
        base = root / dirname
        if not base.exists():
            continue
        files, symlink_skips = safe_files(base, root, kind)
        skipped.extend(symlink_skips)
        for path in files:
            if len(sources) >= max_items:
                return sources, skipped
            if any(part.lower() in FORBIDDEN_PARTS for part in path.parts):
                skipped.append(skip(path, root, "forbidden_source", kind))
            elif path.suffix.lower() not in suffixes:
                skipped.append(skip(path, root, "unsupported_suffix", kind))
            else:
                sources.append(Source(path, relative_to_root(path, root), kind))
    if vault_dir is not None:
        expanded_vault = vault_dir.expanduser()
        for base in curated_vault_dirs(expanded_vault, project_slug):
            if not base.exists():
                continue
            if base.is_symlink():
                skipped.append(vault_skip(base, expanded_vault, "symlink_source"))
                continue
            for current, dirnames, filenames in os.walk(base, followlinks=False):
                current_path = Path(current)
                safe_dirs: list[str] = []
                for dirname in sorted(dirnames):
                    child = current_path / dirname
                    if child.is_symlink():
                        skipped.append(vault_skip(child, expanded_vault, "symlink_source"))
                    else:
                        safe_dirs.append(dirname)
                dirnames[:] = safe_dirs
                for filename in sorted(filenames):
                    path = current_path / filename
                    if path.suffix.lower() != ".md" and not path.is_symlink():
                        continue
                    if path.is_symlink():
                        skipped.append(vault_skip(path, expanded_vault, "symlink_source"))
                        continue
                    if len(sources) >= max_items:
                        return sources, skipped
                    relative = "vault/" + str(path.relative_to(expanded_vault))
                    if any(part.lower() in FORBIDDEN_PARTS for part in path.parts):
                        skipped.append({"source_path": relative, "source_kind": "vault_curated", "reason": "forbidden_source"})
                    else:
                        sources.append(Source(path, relative, "vault_curated"))
    return sources, skipped


def read_source(source: Source) -> tuple[str | None, dict[str, object] | None]:
    try:
        if source.path.is_symlink():
            return None, skip_source(source, "symlink_source")
        if source.path.stat().st_size > MAX_SOURCE_BYTES:
            return None, skip_source(source, "too_large")
        return source.path.read_text(encoding="utf-8"), None
    except OSError:
        return None, skip_source(source, "unreadable")
