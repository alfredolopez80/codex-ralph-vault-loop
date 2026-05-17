from __future__ import annotations

import hashlib
from pathlib import Path

from .paths import append_jsonl, ensure_runtime, now_iso
from .redaction import is_red, redact_text


def digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def save_learning(text: str, source: str, classification: str = "YELLOW") -> Path | None:
    if not text.strip() or classification == "RED" or is_red(text):
        return None
    root = ensure_runtime()
    clean = redact_text(text.strip())
    path = root / "ledgers" / f"learning-{digest(clean)[:12]}.md"
    created = not path.exists()
    if not path.exists():
        path.write_text(
            "\n".join(
                [
                    "---",
                    f'created_at: "{now_iso()}"',
                    f'classification: "{classification}"',
                    f'source: "{source}"',
                    f'hash: "{digest(clean)}"',
                    "---",
                    "",
                    clean,
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if created:
        append_jsonl(root / "ledgers" / "learning-events.jsonl", {"source": source, "path": str(path), "created_at": now_iso()})
    return path


def write_handoff(summary: str, status: str = "stop") -> Path | None:
    if not summary.strip() or is_red(summary):
        return None
    root = ensure_runtime()
    clean = redact_text(summary.strip())
    path = root / "handoffs" / "latest.md"
    content = "\n".join(
        [
            "---",
            f'created_at: "{now_iso()}"',
            f'status: "{status}"',
            'classification: "YELLOW"',
            "---",
            "",
            "# Latest Handoff",
            "",
            clean,
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    archive = root / "handoffs" / f"{now_iso().replace(':', '').replace('+', 'Z')}.md"
    archive.write_text(content, encoding="utf-8")
    return path
