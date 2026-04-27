from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_RALPH_HOME = Path("~/.ralph-codex").expanduser()
CLASSIFICATIONS = {"GREEN", "YELLOW", "RED"}
LAYER_FILES = {
    "L0": "L0_identity.md",
    "L1": "L1_essential.md",
    "L2": "L2_project_rules.md",
    "L3": "L3_vault_index.md",
}


def ralph_home() -> Path:
    return Path(os.environ.get("RALPH_HOME", str(DEFAULT_RALPH_HOME))).expanduser()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_classification(value: str) -> str:
    classification = value.strip().upper()
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"classification must be one of {sorted(CLASSIFICATIONS)}")
    return classification


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = value.strip("-._")
    return value or "note"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def ensure_runtime() -> Path:
    root = ralph_home()
    for relative in ("layers", "ledgers", "handoffs", "reports", "cost"):
        (root / relative).mkdir(parents=True, exist_ok=True)

    defaults = {
        "L0": "# L0 Identity\n\nCodex main decides. External models advise. Gates verify. Vault remembers.\n",
        "L1": "# L1 Essential\n\nRED content stays local and is never saved. Use GREEN/YELLOW only for durable memory.\n",
        "L2": "# L2 Project Rules\n\nNo project rules recorded yet.\n",
        "L3": "# L3 Vault Index\n\nNo vault index loaded yet.\n",
    }
    for layer, filename in LAYER_FILES.items():
        path = root / "layers" / filename
        if not path.exists():
            path.write_text(defaults[layer], encoding="utf-8")
    return root


def read_text(path: Path, limit_chars: int | None = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if limit_chars is not None and len(text) > limit_chars:
        return text[:limit_chars].rstrip() + "\n...[truncated]\n"
    return text


def render_frontmatter(metadata: dict[str, str]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=True)}")
    lines.append("---")
    return "\n".join(lines)


def compact_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip() + " ...[truncated]"
