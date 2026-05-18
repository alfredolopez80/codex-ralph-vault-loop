from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from _vault_common import classify_note, content_hash, init_vault, now_iso, parse_frontmatter, sanitize_slug, vault_dir, yaml_scalar


REPORT_REL = Path("reports/vault-inbox-review")
TARGET_DIRS = ("wiki", "decisions", "sessions", "handoffs")
GLOBAL_MARKERS = ("always", "never", "global", "default behavior", "l1")
DECISION_MARKERS = ("decision:", "decided:", "adr:", "architecture decision")
WIKI_MARKERS = ("knowledge:", "note:", "fact:", "pattern:", "validated:")
SESSION_MARKERS = ("handoff:", "session:")


def ralph_home() -> Path:
    return Path(os.environ.get("RALPH_HOME", "~/.ralph-codex")).expanduser()


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    return text[end + 4 :] if end >= 0 else text


def compact_text(text: str, limit: int = 500) -> str:
    compact = re.sub(r"\s+", " ", strip_frontmatter(text)).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "...[truncated]"


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def inbox_paths(project: str) -> list[Path]:
    inbox = vault_dir() / "projects" / sanitize_slug(project) / "inbox"
    if not inbox.exists():
        return []
    return sorted(path for path in inbox.glob("*.md") if path.is_file())


def curated_paths(project: str) -> list[Path]:
    project_root = vault_dir() / "projects" / sanitize_slug(project)
    paths: list[Path] = []
    for name in TARGET_DIRS:
        paths.extend(sorted((project_root / name).glob("*.md")) if (project_root / name).exists() else [])
    for name in ("wiki", "decisions"):
        paths.extend(sorted((vault_dir() / "global" / name).glob("*.md")) if (vault_dir() / "global" / name).exists() else [])
    layer_root = ralph_home() / "layers"
    paths.extend(sorted(layer_root.glob("*.md")) if layer_root.exists() else [])
    return [path for path in paths if path.is_file()]


def existing_normalized(project: str) -> str:
    chunks = []
    for path in curated_paths(project):
        try:
            chunks.append(normalize(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return "\n".join(chunks)


def target_for(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in GLOBAL_MARKERS):
        return "L1"
    if any(marker in lowered for marker in DECISION_MARKERS):
        return "vault/decisions"
    if any(marker in lowered for marker in SESSION_MARKERS):
        return "vault/sessions"
    if any(marker in lowered for marker in WIKI_MARKERS):
        return "vault/wiki"
    return "none"


def confidence_for(text: str, target: str) -> float:
    lowered = text.lower()
    score = 0.58
    if target in {"vault/decisions", "vault/wiki"}:
        score += 0.12
    if any(marker in lowered for marker in DECISION_MARKERS + WIKI_MARKERS):
        score += 0.12
    if len(text.split()) >= 8:
        score += 0.05
    if target == "L1":
        score = max(score, 0.7)
    if target == "none":
        score -= 0.08
    return round(min(0.9, max(0.0, score)), 2)


def aristotle(reason: str, target: str) -> dict[str, object]:
    return {
        "assumptions_rejected": ["Inbox content is not canonical memory by default."],
        "irreducible_truths": ["RED is never copied.", "Recall-default memory must be scoped and useful."],
        "rebuild_basis": ["Classify first.", "Deduplicate.", "Route only if the target is obvious."],
        "assumption_truth_checks": [f"target={target}", f"reason={reason}"],
        "movement": "Choose the smallest safe useful action: skip, ask the user, or graduate into a scoped curated target.",
    }


def decision_object(
    *,
    source: Path,
    candidate_hash: str,
    decision: str,
    target: str,
    confidence: float,
    reason: str,
    classification: str,
    safe_text: str = "",
    findings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidate_hash": candidate_hash,
        "decision": decision,
        "target": target,
        "confidence": confidence,
        "classification": classification,
        "source_path": str(source),
        "reason": reason,
        "aristotle": aristotle(reason, target),
    }
    if decision != "skip" or classification != "RED":
        payload["candidate_preview"] = compact_text(safe_text, 240)
    if findings:
        payload["findings"] = findings
    return payload


def evaluate_candidate(path: Path, project: str, existing: str) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    metadata = parse_frontmatter(raw)
    requested = metadata.get("classification") or "YELLOW"
    classification, findings, safe_text = classify_note(raw, requested)
    candidate_hash = content_hash(raw)
    if classification == "RED":
        return decision_object(
            source=path,
            candidate_hash=candidate_hash,
            decision="skip",
            target="none",
            confidence=0.0,
            reason="red_classification",
            classification="RED",
            findings=findings,
        )
    text = compact_text(safe_text)
    normalized = normalize(text)
    target = target_for(text)
    confidence = confidence_for(text, target)
    if normalized and normalized in existing:
        return decision_object(
            source=path,
            candidate_hash=candidate_hash,
            decision="skip",
            target=target,
            confidence=confidence,
            reason="duplicate_existing",
            classification=classification,
            safe_text=text,
        )
    if target == "L1":
        return decision_object(
            source=path,
            candidate_hash=candidate_hash,
            decision="ask_user",
            target="L1",
            confidence=confidence,
            reason="l1_or_global_requires_user",
            classification=classification,
            safe_text=text,
        )
    if target in {"vault/decisions", "vault/wiki"} and confidence >= 0.75:
        return decision_object(
            source=path,
            candidate_hash=candidate_hash,
            decision="auto_graduate",
            target=target,
            confidence=confidence,
            reason="high_confidence_project_scoped_target",
            classification=classification,
            safe_text=text,
        )
    if confidence >= 0.6:
        return decision_object(
            source=path,
            candidate_hash=candidate_hash,
            decision="ask_user",
            target=target,
            confidence=confidence,
            reason="ambiguous_or_low_confidence_target",
            classification=classification,
            safe_text=text,
        )
    return decision_object(
        source=path,
        candidate_hash=candidate_hash,
        decision="skip",
        target=target,
        confidence=confidence,
        reason="low_signal",
        classification=classification,
        safe_text=text,
    )


def target_dir(project: str, target: str) -> Path:
    project_root = vault_dir() / "projects" / sanitize_slug(project)
    if target == "vault/decisions":
        return project_root / "decisions"
    if target == "vault/wiki":
        return project_root / "wiki"
    if target == "vault/sessions":
        return project_root / "sessions"
    if target == "vault/handoffs":
        return project_root / "handoffs"
    raise ValueError(f"unsupported graduation target: {target}")


def render_graduated_note(decision: dict[str, Any], project: str) -> str:
    header = {
        "title": str(decision.get("candidate_preview", "Graduated memory"))[:80],
        "classification": decision["classification"],
        "scope": "project",
        "project": sanitize_slug(project),
        "source": "vault-inbox-review",
        "source_hash": decision["candidate_hash"],
        "target": decision["target"],
        "created_at": now_iso(),
    }
    lines = ["---"]
    lines.extend(f"{key}: {yaml_scalar(value)}" for key, value in header.items())
    lines.extend(["---", "", str(decision.get("candidate_preview", "")).strip(), ""])
    return "\n".join(lines)


def graduate(decision: dict[str, Any], project: str) -> Path | None:
    if decision["decision"] != "auto_graduate":
        return None
    directory = target_dir(project, str(decision["target"]))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{str(decision['candidate_hash'])[:12]}.md"
    if not path.exists():
        path.write_text(render_graduated_note(decision, project), encoding="utf-8")
    decision["target_path"] = str(path)
    return path


def append_event(decision: dict[str, Any]) -> None:
    report_dir = ralph_home() / REPORT_REL
    report_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "created_at": now_iso(),
        "candidate_hash": decision["candidate_hash"],
        "decision": decision["decision"],
        "target": decision["target"],
        "confidence": decision["confidence"],
        "reason": decision["reason"],
        "target_path": decision.get("target_path", ""),
    }
    with (report_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def review(project: str, apply: bool = False) -> dict[str, Any]:
    init_vault(project=project)
    existing = existing_normalized(project)
    decisions = [evaluate_candidate(path, project, existing) for path in inbox_paths(project)]
    if apply:
        for decision in decisions:
            graduate(decision, project)
    for decision in decisions:
        append_event(decision)
    report = {
        "created_at": now_iso(),
        "project": sanitize_slug(project),
        "mode": "apply" if apply else "report-only",
        "decisions": decisions,
        "auto_graduate": sum(1 for item in decisions if item["decision"] == "auto_graduate"),
        "ask_user": sum(1 for item in decisions if item["decision"] == "ask_user"),
        "skipped": sum(1 for item in decisions if item["decision"] == "skip"),
    }
    write_report(report)
    return report


def write_report(report: dict[str, Any]) -> None:
    report_dir = ralph_home() / REPORT_REL
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Vault Inbox Review", "", f"Mode: {report['mode']}", f"Project: {report['project']}", ""]
    for decision in report["decisions"]:
        lines.append(
            f"- {decision['decision']} {decision['target']} {float(decision['confidence']):.2f}: {decision['reason']}"
        )
    (report_dir / "latest.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
