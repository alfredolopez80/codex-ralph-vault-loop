from __future__ import annotations

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
            skipped.extend(skip(path, root, "forbidden_source", name) for path in sorted(item for item in base.rglob("*") if item.is_file()))
    for kind, dirname, suffixes in specs:
        base = root / dirname
        if not base.exists():
            continue
        for path in sorted(item for item in base.rglob("*") if item.is_file()):
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
            for path in sorted(item for item in base.rglob("*.md") if item.is_file()):
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
        if source.path.stat().st_size > MAX_SOURCE_BYTES:
            return None, skip_source(source, "too_large")
        return source.path.read_text(encoding="utf-8"), None
    except OSError:
        return None, skip_source(source, "unreadable")
