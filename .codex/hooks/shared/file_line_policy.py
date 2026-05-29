from __future__ import annotations

import os
import re
from pathlib import Path

from .paths import write_json


DEFAULT_LINE_LIMIT = 350
SENSITIVE_PATH_RE = re.compile(r"(?i)(^|/)(\.env|id_rsa|id_ed25519|[^/]*(secret|token|credential|wallet|keystore)[^/]*)($|/)")

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
}

GENERATED_NAMES = {
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "poetry.lock",
    "uv.lock",
    "cargo.lock",
    "go.sum",
}

GENERATED_SUFFIXES = {
    ".lock",
    ".lockb",
    ".map",
    ".min.js",
    ".min.css",
    ".snap",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".tgz",
    ".wasm",
}


def line_limit() -> int:
    raw = os.environ.get("RALPH_FILE_LINE_LIMIT", str(DEFAULT_LINE_LIMIT))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_LINE_LIMIT
    return value if value > 0 else DEFAULT_LINE_LIMIT


def should_skip(path: Path, root: Path) -> bool:
    name = path.name.lower()
    if SENSITIVE_PATH_RE.search(path.as_posix()):
        return True
    if name in GENERATED_NAMES or any(name.endswith(suffix) for suffix in GENERATED_SUFFIXES):
        return True
    if path.is_symlink() or not path.is_file():
        return True
    try:
        parts = set(path.relative_to(root).parts)
    except ValueError:
        parts = set(path.parts)
    return bool(parts & SKIP_DIRS)


def count_lines(path: Path) -> int | None:
    try:
        with path.open("rb") as handle:
            sample = handle.read(4096)
            if b"\0" in sample:
                return None
            handle.seek(0)
            return sum(1 for _ in handle)
    except OSError:
        return None


def oversized(paths: set[Path], root: Path, limit: int) -> list[tuple[Path, int]]:
    findings: list[tuple[Path, int]] = []
    for path in sorted(paths):
        if should_skip(path, root):
            continue
        lines = count_lines(path)
        if lines is not None and lines > limit:
            findings.append((path, lines))
    return findings


def guidance(limit: int) -> str:
    return (
        f"Ralph file-line guard blocks files over {limit} lines. Split the file before continuing: "
        "keep behavior stable with tests before/after, extract by domain/use-case/component boundary, "
        "avoid generic utils/helpers dumping grounds, preserve validation/auth/secrets and trust boundaries, "
        "avoid sec-context anti-patterns while moving code, and keep the smallest useful Kaizen refactor. "
        "For React/Next files, prefer one component per file, "
        "colocated private helpers, extracted use* hooks for shared logic, direct imports over barrels, "
        "and dynamic imports for heavy UI."
    )


def emit_block(findings: list[tuple[Path, int]], limit: int) -> None:
    files = [f"{path} ({lines} lines)" for path, lines in findings[:8]]
    more = len(findings) - len(files)
    details = " Oversized files: " + "; ".join(files) + "."
    suffix = f" Additional oversized files: {more}." if more > 0 else ""
    write_json({"decision": "block", "reason": guidance(limit) + details + suffix})
