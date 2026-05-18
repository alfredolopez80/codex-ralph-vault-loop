from __future__ import annotations

import json
import os
import re
from pathlib import Path

from _memory_common import LAYER_FILES, render_frontmatter


DREAM_STATE_MIN_CONFIDENCE = 0.6
DREAM_STATE_MAX_CANDIDATES = 12
DEFAULT_VAULT_DIR = Path("~/Documents/Obsidian/MiVault").expanduser()


def render_markdown(report: dict[str, object]) -> str:
    candidates = report["candidates"]
    skipped = report["skipped"]
    metadata = {
        "created_at": str(report["created_at"]),
        "classification": str(report["classification"]),
        "source_count": str(report["source_count"]),
        "red_skipped": str(report["red_skipped"]),
        "mode": str(report["mode"]),
    }
    lines = [render_frontmatter(metadata), "", "# Ralph Memory Dream", "", "## Summary", ""]
    lines.append(f"- Consolidated {len(candidates)} safe memory candidates.")
    lines.append(f"- Skipped {len(skipped)} RED/sensitive inputs.")
    lines.append(f"- Found {report['duplicate_count']} duplicate or existing entries.")
    lines.append("")
    append_candidate_sections(lines, candidates)
    append_evidence(lines, candidates)
    append_skipped(lines, skipped)
    return "\n".join(lines).rstrip() + "\n"


def append_candidate_sections(lines: list[str], candidates: list[dict[str, object]]) -> None:
    titles = {"L1": "Candidate L1 Updates", "L2": "Candidate L2 Project Rules", "L3": "Candidate L3 Vault Index Updates"}
    for target, title in titles.items():
        target_candidates = [candidate for candidate in candidates if candidate["target_layer"] == target]
        lines.extend([f"## {title}", ""])
        lines.extend(f"- {candidate['text']}" for candidate in target_candidates)
        if not target_candidates:
            lines.append("No candidate updates.")
        lines.append("")
    report_only = [candidate for candidate in candidates if candidate["target_layer"] == "report-only"]
    if report_only:
        lines.extend(["## Report Only", ""])
        lines.extend(f"- {candidate['text']}" for candidate in report_only)
        lines.append("")


def append_evidence(lines: list[str], candidates: list[dict[str, object]]) -> None:
    lines.extend(["## Evidence", "", "| Candidate | Sources | Classification | Confidence |", "|---|---:|---|---:|"])
    for candidate in candidates:
        text = str(candidate["text"]).replace("|", "\\|")
        lines.append(f"| {text} | {len(candidate['source_paths'])} | {candidate['classification']} | {candidate['confidence']:.2f} |")


def append_skipped(lines: list[str], skipped: list[dict[str, object]]) -> None:
    lines.extend(["", "## Skipped", ""])
    if not skipped:
        lines.append("No skipped RED inputs.")
        return
    for item in skipped:
        labels = ", ".join(finding["label"] for finding in item["findings"])
        lines.append(f"- RED item skipped: hash={str(item['hash'])[:12]}, finding={labels}")


def write_reports(root: Path, report: dict[str, object], emit_patch: bool) -> tuple[Path, Path]:
    reports_dir = root / "reports" / "memory"
    archive_dir = reports_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = str(report["created_at"]).replace(":", "").replace("+", "Z")
    json_path = reports_dir / "dream-latest.json"
    md_path = reports_dir / "dream-latest.md"
    json_text = json.dumps(report, indent=2, sort_keys=True)
    md_text = render_markdown(report)
    json_path.write_text(json_text + "\n", encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    (archive_dir / f"{timestamp}.json").write_text(json_text + "\n", encoding="utf-8")
    (archive_dir / f"{timestamp}.md").write_text(md_text, encoding="utf-8")
    if emit_patch:
        (reports_dir / "dream-layer-patch.md").write_text(render_layer_patch(report), encoding="utf-8")
    return md_path, json_path


def dream_state_candidates(report: dict[str, object]) -> list[dict[str, object]]:
    candidates = []
    for candidate in report["candidates"]:
        if candidate["duplicate_existing"] or candidate["target_layer"] not in {"L1", "L2", "L3"}:
            continue
        if float(candidate["confidence"]) >= DREAM_STATE_MIN_CONFIDENCE:
            candidates.append(candidate)
    return candidates[:DREAM_STATE_MAX_CANDIDATES]


def write_dream_state(root: Path, report: dict[str, object]) -> tuple[Path, Path]:
    candidates = dream_state_candidates(report)
    state = {
        "created_at": report["created_at"],
        "classification": "YELLOW",
        "source_report": str(root / "reports" / "memory" / "dream-latest.json"),
        "policy": {"min_confidence": DREAM_STATE_MIN_CONFIDENCE, "max_candidates": DREAM_STATE_MAX_CANDIDATES, "auto_canonical": False},
        "candidates": candidates,
    }
    json_path = root / "layers" / "L4_dream_state.json"
    md_path = root / "layers" / "L4_dream_state.md"
    json_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# L4 Dream State",
        "",
        "This is auto-generated from safe Ralph Memory Dream candidates. It is loaded by wakeup.py but is not canonical L1/L2/L3 memory.",
        "",
        f"Generated: {report['created_at']}",
        f"Policy: confidence >= {DREAM_STATE_MIN_CONFIDENCE}, max {DREAM_STATE_MAX_CANDIDATES} candidates, no auto-canonical promotion.",
        "",
    ]
    lines.extend(render_state_candidates(candidates))
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return md_path, json_path


def render_state_candidates(candidates: list[dict[str, object]]) -> list[str]:
    if not candidates:
        return ["No dream candidates met the auto-use threshold."]
    lines = ["## Active Dream Learnings", ""]
    for candidate in candidates:
        lines.append(f"- [{candidate['target_layer']} candidate, confidence {candidate['confidence']:.2f}] {candidate['text']}")
    return lines


def write_vault_inbox(report: dict[str, object], project: str) -> Path:
    inbox = vault_root() / "projects" / slug(project) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    timestamp = str(report["created_at"]).replace(":", "").replace("+", "Z")
    path = inbox / f"dream-{timestamp}.md"
    path.write_text(render_vault_inbox(report, project), encoding="utf-8")
    return path


def render_vault_inbox(report: dict[str, object], project: str) -> str:
    candidates = dream_state_candidates(report)
    lines = [
        "---",
        f'title: "Ralph Memory Dream {report["created_at"]}"',
        'classification: "YELLOW"',
        f'project: "{slug(project)}"',
        f'source_project_id: "{report.get("source_project_id", "")}"',
        f'source_project_slug: "{report.get("source_project_slug", slug(project))}"',
        f'source_workspace_root: "{report.get("source_workspace_root", "")}"',
        'source: "ralph-memory-dream"',
        f'created_at: "{report["created_at"]}"',
        "---",
        "",
        "# Ralph Memory Dream Inbox",
        "",
        "Review these candidates before promoting anything into canonical vault notes or L1-L3 memory.",
        "",
        "## Summary",
        "",
        f"- Safe sources: {report['safe_source_count']}",
        f"- RED skipped: {report['red_skipped']}",
        f"- Auto-use candidates: {len(candidates)}",
        "",
        "## Candidates",
        "",
    ]
    lines.extend(render_inbox_candidates(candidates))
    append_skipped(lines, report["skipped"])
    return "\n".join(lines).rstrip() + "\n"


def render_inbox_candidates(candidates: list[dict[str, object]]) -> list[str]:
    if not candidates:
        return ["No candidates met the auto-use threshold."]
    return [f"- [{candidate['target_layer']}, confidence {candidate['confidence']:.2f}] {candidate['text']}" for candidate in candidates]


def render_layer_patch(report: dict[str, object]) -> str:
    lines = ["# Ralph Memory Dream Layer Patch", ""]
    for target in ("L1", "L2", "L3"):
        candidates = [candidate for candidate in report["candidates"] if candidate["target_layer"] == target]
        lines.extend([f"## Proposed patch for {LAYER_FILES[target]}", ""])
        for candidate in candidates:
            lines.extend([f"<!-- dream-candidate: {candidate['hash']} -->", f"- {candidate['text']}"])
        if not candidates:
            lines.append("No candidate updates.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def vault_root() -> Path:
    return Path(os.environ.get("VAULT_DIR", str(DEFAULT_VAULT_DIR))).expanduser()


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return normalized or "default"
