from __future__ import annotations

import hashlib
from pathlib import Path

from .active_context import ActiveContext, ensure_project_runtime
from .paths import append_jsonl, ensure_runtime, now_iso
from .redaction import is_red, redact_text


def digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def runtime_root(context: ActiveContext | None = None) -> Path:
    return ensure_project_runtime(context) if context is not None else ensure_runtime()


def learning_trust_status(context: ActiveContext | None) -> str:
    if context and context.project_slug and context.branch and context.sha and context.session_id:
        return "trusted"
    return "provisional"


def save_learning(text: str, source: str, classification: str = "YELLOW", context: ActiveContext | None = None) -> Path | None:
    if not text.strip() or classification == "RED" or is_red(text):
        return None
    root = runtime_root(context)
    clean = redact_text(text.strip())
    path = root / "ledgers" / f"learning-{digest(clean)[:12]}.md"
    created = not path.exists()
    trust_status = learning_trust_status(context)
    confidence = "0.80" if trust_status == "trusted" else "0.40"
    if not path.exists():
        path.write_text(
            "\n".join(
                [
                    "---",
                    f'created_at: "{now_iso()}"',
                    f'updated_at: "{now_iso()}"',
                    f'classification: "{classification}"',
                    'memory_kind: "validated_learning"',
                    f'trust_status: "{trust_status}"',
                    f'provisional: "{str(trust_status == "provisional").lower()}"',
                    'deprecated: "false"',
                    'stale: "false"',
                    f'confidence: "{confidence}"',
                    f'source: "{source}"',
                    f'project_id: "{context.project_id if context else ""}"',
                    f'project: "{context.project_slug if context else ""}"',
                    f'repo: "{context.project_slug if context else ""}"',
                    f'branch: "{context.branch if context else ""}"',
                    f'commit: "{context.sha if context else ""}"',
                    f'session_id: "{context.session_id if context else ""}"',
                    f'workspace_instance_id: "{context.workspace_instance_id if context else ""}"',
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
        append_jsonl(
            root / "ledgers" / "learning-events.jsonl",
            {
                "source": source,
                "path": str(path),
                "created_at": now_iso(),
                "trust_status": trust_status,
                "confidence": confidence,
                "project_id": context.project_id if context else "",
                "project": context.project_slug if context else "",
                "repo": context.project_slug if context else "",
                "branch": context.branch if context else "",
                "commit": context.sha if context else "",
                "session_id": context.session_id if context else "",
            },
        )
    return path


def write_handoff(summary: str, status: str = "stop", next_step: str = "", context: ActiveContext | None = None) -> Path | None:
    if not summary.strip() or is_red(summary) or is_red(next_step):
        return None
    root = runtime_root(context)
    clean = redact_text(summary.strip())
    clean_next = redact_text(next_step.strip())
    body = [
        "---",
        f'created_at: "{now_iso()}"',
        f'status: "{status}"',
                'memory_kind: "operational_handoff"',
                'trust_status: "provisional"',
                'provisional: "true"',
                'deprecated: "false"',
                'stale: "false"',
                'confidence: "0.40"',
                f'source: "{status}"',
                'classification: "YELLOW"',
                f'project_id: "{context.project_id if context else ""}"',
                f'project: "{context.project_slug if context else ""}"',
                f'repo: "{context.project_slug if context else ""}"',
                f'session_id: "{context.session_id if context else ""}"',
                f'workspace_instance_id: "{context.workspace_instance_id if context else ""}"',
                f'branch: "{context.branch if context else ""}"',
                f'commit: "{context.sha if context else ""}"',
                f'git_branch: "{context.branch if context else ""}"',
                f'git_sha: "{context.sha if context else ""}"',
                "---",
        "",
        "# Latest Handoff",
        "",
        clean,
    ]
    if clean_next:
        body.extend(["", "Next:", "", clean_next])
    body.append("")
    path = root / "handoffs" / "latest.md"
    content = "\n".join(body)
    path.write_text(content, encoding="utf-8")
    archive = root / "handoffs" / f"{now_iso().replace(':', '').replace('+', 'Z')}.md"
    archive.write_text(content, encoding="utf-8")
    return path
