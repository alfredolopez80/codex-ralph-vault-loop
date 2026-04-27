from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_VAULT_DIR = Path("~/Documents/Obsidian/MiVault").expanduser()
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_SOURCE_DIR = REPO_ROOT / "templates" / "vault"
CLASSIFICATIONS = {"GREEN", "YELLOW", "RED"}


def vault_dir() -> Path:
    return Path(os.environ.get("VAULT_DIR", str(DEFAULT_VAULT_DIR))).expanduser()


def default_project() -> str:
    return sanitize_slug(os.environ.get("VAULT_PROJECT") or Path.cwd().name or "default")


def default_agent() -> str:
    return sanitize_slug(os.environ.get("VAULT_AGENT") or "codex")


def sanitize_slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = value.strip("-._")
    return value or "default"


def normalize_classification(value: str) -> str:
    classification = value.strip().upper()
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"classification must be one of {sorted(CLASSIFICATIONS)}")
    return classification


def content_hash(text: str) -> str:
    normalized = text.strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def yaml_scalar(value: object) -> str:
    return json.dumps("" if value is None else str(value), ensure_ascii=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def required_dirs(project: str | None = None, agent: str | None = None) -> list[Path]:
    project = sanitize_slug(project or default_project())
    agent = sanitize_slug(agent or default_agent())
    raw = [
        "global/raw",
        "global/wiki",
        "global/decisions",
        f"projects/{project}/raw",
        f"projects/{project}/wiki",
        f"projects/{project}/sessions",
        f"projects/{project}/handoffs",
        f"agents/{agent}/diary",
        "_templates",
    ]
    return [vault_dir() / item for item in raw]


def init_vault(project: str | None = None, agent: str | None = None) -> list[Path]:
    created = []
    for directory in required_dirs(project, agent):
        directory.mkdir(parents=True, exist_ok=True)
        created.append(directory)
    return created


def copy_vault_templates() -> list[Path]:
    target_dir = vault_dir() / "_templates"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    if not TEMPLATE_SOURCE_DIR.exists():
        return copied
    for source in sorted(TEMPLATE_SOURCE_DIR.glob("*.md")):
        target = target_dir / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        copied.append(target)
    return copied


def note_path(classification: str, digest: str, project: str | None = None) -> Path:
    classification = normalize_classification(classification)
    if classification == "GREEN":
        return vault_dir() / "global" / "raw" / f"{digest}.md"
    if classification == "YELLOW":
        return vault_dir() / "projects" / sanitize_slug(project or default_project()) / "raw" / f"{digest}.md"
    raise ValueError("RED notes must not be persisted")


def title_from_text(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Untitled note")
    return first_line[:80]


def render_note(
    *,
    text: str,
    classification: str,
    project: str | None,
    agent: str | None,
    source: str,
    title: str | None,
) -> str:
    classification = normalize_classification(classification)
    digest = content_hash(text)
    project_slug = sanitize_slug(project or default_project())
    agent_slug = sanitize_slug(agent or default_agent())
    scope = "global" if classification == "GREEN" else "project"
    header = {
        "title": title or title_from_text(text),
        "classification": classification,
        "scope": scope,
        "project": "" if scope == "global" else project_slug,
        "agent": agent_slug,
        "hash": digest,
        "source": source,
        "created_at": now_iso(),
    }
    lines = ["---"]
    lines.extend(f"{key}: {yaml_scalar(value)}" for key, value in header.items())
    lines.extend(["---", "", text.strip(), ""])
    return "\n".join(lines)


def iter_markdown_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata
