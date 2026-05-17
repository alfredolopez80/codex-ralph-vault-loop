#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RALPH_HOME = Path("~/.ralph-codex").expanduser()
DEFAULT_VAULT_DIR = Path("~/Documents/Obsidian/MiVault").expanduser()
SKIP_PATH_PARTS = (
    ".env",
    "id_rsa",
    "id_ed25519",
)
SKIP_PATH_SUBSTRINGS = (
    "secrets",
    "token",
    "credential",
    "wallet",
    "keystore",
)
PREVIEW_CHARS = 260


@dataclass(frozen=True)
class Source:
    path: Path
    root: Path | None = None


@dataclass(frozen=True)
class Result:
    path: str
    score: int
    preview: str


def load_sensitive_classifier():
    security_dir = REPO_ROOT / "scripts" / "security"
    if str(security_dir) not in sys.path:
        sys.path.insert(0, str(security_dir))
    try:
        from sensitive_content import classify_text  # type: ignore
    except Exception:
        return None
    return classify_text


def env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser()


def project_default() -> str:
    return os.environ.get("VAULT_PROJECT") or REPO_ROOT.name


def safe_project(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or REPO_ROOT.name


def path_is_sensitive(path: Path) -> bool:
    lowered_parts = [part.lower() for part in path.parts]
    lowered_text = str(path).lower()
    return any(part in lowered_parts for part in SKIP_PATH_PARTS) or any(
        part in lowered_text for part in SKIP_PATH_SUBSTRINGS
    )


def iter_existing_files(paths: Iterable[Source]) -> Iterable[Source]:
    for source in paths:
        if source.path.is_file() and not path_is_sensitive(source.path):
            yield source


def iter_markdown_tree(root: Path) -> Iterable[Source]:
    if not root.exists() or path_is_sensitive(root):
        return
    for path in sorted(root.rglob("*.md")):
        if path.is_file() and not path_is_sensitive(path):
            yield Source(path, root)


def iter_skill_files() -> Iterable[Source]:
    root = REPO_ROOT / ".agents" / "skills"
    if not root.exists():
        return
    for path in sorted(root.glob("*/SKILL.md")):
        if path.is_file() and not path_is_sensitive(path):
            yield Source(path, REPO_ROOT)


def source_paths(project: str, include_raw: bool) -> Iterable[Source]:
    ralph_home = env_path("RALPH_HOME", DEFAULT_RALPH_HOME)
    vault = env_path("VAULT_DIR", DEFAULT_VAULT_DIR)
    project = safe_project(project)

    yield from iter_existing_files(
        [
            Source(REPO_ROOT / "AGENTS.md", REPO_ROOT),
            Source(REPO_ROOT / "CLAUDE.md", REPO_ROOT),
        ]
    )
    yield from iter_skill_files()
    yield from iter_markdown_tree(ralph_home / "layers")
    yield from iter_markdown_tree(ralph_home / "handoffs")
    yield from iter_markdown_tree(ralph_home / "ledgers")

    curated_vault_dirs = [
        vault / "global" / "wiki",
        vault / "global" / "decisions",
        vault / "projects" / project / "wiki",
        vault / "projects" / project / "decisions",
        vault / "projects" / project / "sessions",
        vault / "projects" / project / "handoffs",
    ]
    if include_raw:
        curated_vault_dirs.extend(
            [
                vault / "global" / "raw",
                vault / "global" / "inbox",
                vault / "projects" / project / "raw",
                vault / "projects" / project / "inbox",
            ]
        )
    for directory in curated_vault_dirs:
        yield from iter_markdown_tree(directory)


def display_path(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return str(path.relative_to(root))
        except ValueError:
            pass
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9_./-]+", value.lower()) if len(token) > 1]


def score_text(query: str, text: str, path: str) -> int:
    query_terms = tokenize(query)
    if not query_terms:
        return 0
    text_lower = text.lower()
    path_lower = path.lower()
    score = 0
    for term in query_terms:
        score += min(text_lower.count(term), 10) * 3
        if term in path_lower:
            score += 8
    if query.lower() in text_lower:
        score += 20
    return score


def compact_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def preview_for(query: str, text: str) -> str:
    text = compact_space(text)
    if len(text) <= PREVIEW_CHARS:
        return text
    positions = [text.lower().find(term) for term in tokenize(query)]
    positions = [position for position in positions if position >= 0]
    start = max(0, min(positions) - 70) if positions else 0
    end = min(len(text), start + PREVIEW_CHARS)
    preview = text[start:end].strip()
    if start > 0:
        preview = "... " + preview
    if end < len(text):
        preview += " ..."
    return preview


def safe_text_for_output(text: str, classifier) -> tuple[str | None, bool]:
    if classifier is None:
        return text, False
    report = classifier(text)
    if getattr(report, "classification", "GREEN") == "RED":
        return None, True
    return getattr(report, "redacted_text", text), getattr(report, "changed", False)


def collect_results(query: str, project: str, limit: int, include_raw: bool) -> list[Result]:
    classifier = load_sensitive_classifier()
    results: list[Result] = []
    seen: set[Path] = set()
    for source in source_paths(project, include_raw):
        if source.path in seen:
            continue
        seen.add(source.path)
        try:
            raw_text = source.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        safe_text, skipped_red = safe_text_for_output(raw_text, classifier)
        if skipped_red or safe_text is None:
            continue
        path = display_path(source.path, source.root)
        score = score_text(query, safe_text, path)
        if score <= 0:
            continue
        results.append(Result(path=path, score=score, preview=preview_for(query, safe_text)))
    results.sort(key=lambda item: (-item.score, item.path))
    return results[: max(limit, 0)]


def render_markdown(query: str, project: str, results: list[Result]) -> str:
    lines = [
        "# Ralph Recall",
        "",
        f"- query: `{query}`",
        f"- project: `{project}`",
        "- note: recall is context, not authority",
        "",
        "## Results",
        "",
    ]
    if not results:
        lines.append("No safe matches found.")
        return "\n".join(lines) + "\n"
    for result in results:
        lines.extend(
            [
                f"### {result.path}",
                f"- score: `{result.score}`",
                f"- safe preview: {result.preview}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall safe local Ralph memory context.")
    parser.add_argument("query")
    parser.add_argument("--project", default=project_default())
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--include-raw", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    project = safe_project(args.project)
    results = collect_results(args.query, project, args.limit, args.include_raw)
    if args.json:
        print(
            json.dumps(
                {
                    "query": args.query,
                    "project": project,
                    "note": "recall is context, not authority",
                    "results": [result.__dict__ for result in results],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_markdown(args.query, project, results), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
