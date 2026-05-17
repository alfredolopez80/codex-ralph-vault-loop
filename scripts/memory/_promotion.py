from __future__ import annotations

import json
from pathlib import Path

from _memory_common import LAYER_FILES, content_hash, now_iso, read_text
from _dream_core import normalize_candidate


AUTO_PROMOTE_MIN_CONFIDENCE = 0.8
REVIEW_MIN_CONFIDENCE = 0.6
AUTO_PROMOTE_TARGETS = {"L2", "L3"}
TARGET_LAYERS = {"L1", "L2", "L3"}
PROMOTION_EVENTS = Path("reports/memory/promotion-events.jsonl")
PROMOTION_LATEST_JSON = Path("reports/memory/promotion-latest.json")
PROMOTION_LATEST_MD = Path("reports/memory/promotion-latest.md")


def _event_key(event: dict[str, object]) -> tuple[str, str]:
    return (str(event.get("candidate_hash") or ""), str(event.get("decision") or ""))


def load_promotion_events(root: Path) -> list[dict[str, object]]:
    text = read_text(root / PROMOTION_EVENTS)
    events: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def append_promotion_event(root: Path, event: dict[str, object]) -> None:
    path = root / PROMOTION_EVENTS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")


def layer_contains_candidate(root: Path, candidate: dict[str, object]) -> bool:
    target = str(candidate["target_layer"])
    text = str(candidate["text"])
    layer = root / "layers" / LAYER_FILES[target]
    current = read_text(layer)
    marker = f"ralph-promotion:{candidate['hash']}"
    return marker in current or normalize_candidate(text) in normalize_candidate(current)


def append_to_layer(root: Path, candidate: dict[str, object]) -> None:
    target = str(candidate["target_layer"])
    layer = root / "layers" / LAYER_FILES[target]
    current = read_text(layer).rstrip()
    block = "\n".join(
        [
            f"<!-- ralph-promotion:{candidate['hash']} target={target} confidence={float(candidate['confidence']):.2f} -->",
            f"- {candidate['text']}",
        ]
    )
    heading = "## Auto-Promoted Learnings"
    if heading not in current:
        current = current + f"\n\n{heading}\n\n{block}"
    else:
        current = current + f"\n\n{block}"
    layer.write_text(current.rstrip() + "\n", encoding="utf-8")


def decide_candidate(candidate: dict[str, object]) -> tuple[str, str]:
    target = str(candidate["target_layer"])
    confidence = float(candidate["confidence"])
    classification = str(candidate["classification"])
    source_groups = {str(group) for group in candidate.get("source_groups", [])}
    if classification == "RED":
        return "skip", "red_classification"
    if target not in TARGET_LAYERS:
        return "skip", "report_only"
    if bool(candidate["duplicate_existing"]):
        return "skip", "duplicate_existing"
    if target in AUTO_PROMOTE_TARGETS and confidence >= AUTO_PROMOTE_MIN_CONFIDENCE:
        if {"handoffs", "ledgers"}.issubset(source_groups):
            return "auto_promote", "high_confidence_runtime_correlated_candidate"
        return "review", "high_confidence_needs_runtime_corroboration"
    if confidence >= REVIEW_MIN_CONFIDENCE:
        return "review", "needs_human_or_model_review"
    return "skip", "low_confidence"


def summarize_promotions(root: Path, report: dict[str, object]) -> dict[str, object]:
    existing_events = load_promotion_events(root)
    seen_events = {_event_key(event) for event in existing_events}
    auto_promoted: list[dict[str, object]] = []
    review_requested: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    created_at = now_iso()

    for candidate in report["candidates"]:
        decision, reason = decide_candidate(candidate)
        candidate_hash = str(candidate["hash"])
        result = {**candidate, "decision": decision, "reason": reason}
        if decision == "auto_promote":
            if layer_contains_candidate(root, candidate):
                result["decision"] = "skip"
                result["reason"] = "already_in_layer"
                skipped.append(result)
                continue
            append_to_layer(root, candidate)
            event = {
                "created_at": created_at,
                "decision": "auto_promoted",
                "candidate_hash": candidate_hash,
                "target_layer": candidate["target_layer"],
                "confidence": candidate["confidence"],
                "source_paths": candidate["source_paths"],
                "source_groups": candidate.get("source_groups", []),
                "text_hash": content_hash(str(candidate["text"])),
            }
            if _event_key(event) not in seen_events:
                append_promotion_event(root, event)
                seen_events.add(_event_key(event))
            result["decision"] = "auto_promoted"
            auto_promoted.append(result)
            continue
        if decision == "review":
            event = {
                "created_at": created_at,
                "decision": "review_requested",
                "candidate_hash": candidate_hash,
                "target_layer": candidate["target_layer"],
                "confidence": candidate["confidence"],
                "source_paths": candidate["source_paths"],
                "source_groups": candidate.get("source_groups", []),
                "text_hash": content_hash(str(candidate["text"])),
            }
            if _event_key(event) not in seen_events:
                append_promotion_event(root, event)
                seen_events.add(_event_key(event))
            review_requested.append(result)
            continue
        skipped.append(result)

    summary = {
        "created_at": created_at,
        "source_report": str(root / "reports" / "memory" / "dream-latest.json"),
        "policy": {
            "auto_promote_min_confidence": AUTO_PROMOTE_MIN_CONFIDENCE,
            "review_min_confidence": REVIEW_MIN_CONFIDENCE,
            "auto_promote_targets": sorted(AUTO_PROMOTE_TARGETS),
            "l1_requires_review": True,
        },
        "auto_promoted": auto_promoted,
        "review_requested": review_requested,
        "skipped": skipped,
    }
    write_promotion_summary(root, summary)
    return summary


def write_promotion_summary(root: Path, summary: dict[str, object]) -> None:
    json_path = root / PROMOTION_LATEST_JSON
    md_path = root / PROMOTION_LATEST_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_promotion_summary(summary), encoding="utf-8")


def render_promotion_summary(summary: dict[str, object]) -> str:
    lines = [
        "# Ralph Memory Promotion",
        "",
        f"Generated: {summary['created_at']}",
        "",
        "## Auto Promoted",
        "",
    ]
    auto_promoted = summary["auto_promoted"]
    if auto_promoted:
        for candidate in auto_promoted:
            lines.append(f"- [{candidate['target_layer']}, {float(candidate['confidence']):.2f}] {candidate['text']}")
    else:
        lines.append("No candidates auto-promoted.")
    lines.extend(["", "## Review Requested", ""])
    review_requested = summary["review_requested"]
    if review_requested:
        for candidate in review_requested:
            lines.append(f"- [{candidate['target_layer']}, {float(candidate['confidence']):.2f}] {candidate['text']}")
    else:
        lines.append("No candidates need review.")
    return "\n".join(lines).rstrip() + "\n"
