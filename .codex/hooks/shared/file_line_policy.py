from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .paths import write_json


DEFAULT_LINE_LIMIT = 350
EXISTING_SOURCE_LINE_LIMIT = 1000
DOCUMENT_LINE_LIMIT = 5000
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

SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".m",
    ".mm",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
}

DOCUMENT_SUFFIXES = {
    ".htm",
    ".html",
    ".markdown",
    ".md",
    ".mdx",
}

PLAN_OR_NOTE_NAME_RE = re.compile(
    r"(?i)(implementation[-_ ]?notes?|plan|handoff|future[-_ ].*|notes?)"
)
PLAN_OR_NOTE_DIRS = {
    ".local-notes",
    ".ralph",
    "plans",
}


@dataclass(frozen=True)
class FileLinePolicy:
    limit: int
    category: str
    blocks: bool = True


@dataclass(frozen=True)
class FileLineFinding:
    path: Path
    lines: int
    policy: FileLinePolicy


def line_limit() -> int:
    raw = os.environ.get("RALPH_FILE_LINE_LIMIT", str(DEFAULT_LINE_LIMIT))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_LINE_LIMIT
    return value if value > 0 else DEFAULT_LINE_LIMIT


def document_line_limit() -> int:
    raw = os.environ.get("RALPH_DOCUMENT_LINE_LIMIT", str(DOCUMENT_LINE_LIMIT))
    try:
        value = int(raw)
    except ValueError:
        return DOCUMENT_LINE_LIMIT
    return value if value > 0 else DOCUMENT_LINE_LIMIT


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


def relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    try:
        return path.relative_to(root).parts
    except ValueError:
        return path.parts


def is_plan_or_note(path: Path, root: Path) -> bool:
    parts = relative_parts(path, root)
    lower_parts = {part.lower() for part in parts}
    if lower_parts & PLAN_OR_NOTE_DIRS:
        return True
    return any(PLAN_OR_NOTE_NAME_RE.search(part) for part in parts)


def is_git_tracked(path: Path, root: Path) -> bool:
    try:
        git_path = str(path.relative_to(root))
    except ValueError:
        return False
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", git_path],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    return result.returncode == 0


def file_policy(path: Path, root: Path) -> FileLinePolicy:
    if is_plan_or_note(path, root):
        return FileLinePolicy(document_line_limit(), "plan/implementation note")

    suffix = path.suffix.lower()
    if suffix in DOCUMENT_SUFFIXES:
        return FileLinePolicy(document_line_limit(), "document")

    if suffix == ".json":
        return FileLinePolicy(line_limit(), "structured JSON")

    if suffix in SOURCE_SUFFIXES and is_git_tracked(path, root):
        return FileLinePolicy(EXISTING_SOURCE_LINE_LIMIT, "existing source/test file refactor threshold", blocks=False)

    return FileLinePolicy(line_limit(), "new source/test file")


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


def oversized(paths: set[Path], root: Path, limit: int | None = None) -> list[FileLineFinding]:
    findings: list[FileLineFinding] = []
    for path in sorted(paths):
        if should_skip(path, root):
            continue
        lines = count_lines(path)
        if lines is None:
            continue
        policy = file_policy(path, root)
        if limit is not None and policy.limit == DEFAULT_LINE_LIMIT:
            policy = FileLinePolicy(limit, policy.category)
        if lines > policy.limit and policy.blocks:
            findings.append(FileLineFinding(path, lines, policy))
    return findings


def guidance() -> str:
    return (
        "Ralph file-line guard blocks oversized files by category: new source/test files over "
        f"{line_limit()} lines, documents/plans/implementation notes over {document_line_limit()} lines, "
        "and large non-generated JSON "
        "unless it belongs to a plan or note. Split the file before continuing. For source/JSON, keep behavior stable "
        "with tests before/after, extract by domain/use-case/component boundary, "
        "avoid generic utils/helpers dumping grounds, preserve validation/auth/secrets and trust boundaries, "
        "avoid sec-context anti-patterns while moving code, and keep the smallest useful Kaizen refactor. "
        f"Existing tracked source/test files over {EXISTING_SOURCE_LINE_LIMIT} lines are allowed for punctual edits; "
        "recommend a refactor when the needed cleanup is small and affects few files, execute it only with explicit "
        "user approval, and write a .local-notes/ follow-up when the refactor is broad or outside the current PR goal. "
        "For React/Next files, prefer one component per file, "
        "colocated private helpers, extracted use* hooks for shared logic, direct imports over barrels, "
        "and dynamic imports for heavy UI."
    )


def emit_block(findings: list[FileLineFinding], limit: int | None = None) -> None:
    files = [
        f"{finding.path} ({finding.lines} lines, limit {finding.policy.limit}, {finding.policy.category})"
        for finding in findings[:8]
    ]
    more = len(findings) - len(files)
    details = " Oversized files: " + "; ".join(files) + "."
    suffix = f" Additional oversized files: {more}." if more > 0 else ""
    write_json({"decision": "block", "reason": guidance() + details + suffix})
