#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
for import_dir in (SCRIPT_DIR, REPO_ROOT / ".codex" / "hooks"):
    if str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))

from memory_node import MemoryNode, MemoryNodeValidationError, contains_red_material, sha256_text  # noqa: E402
from tree_store import TreeStore  # noqa: E402
from usage_ledger import record_usage  # noqa: E402

try:
    from shared.active_context import active_context_from_payload  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover
    active_context_from_payload = None

STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "what", "when", "where", "into", "node", "memory", "does", "exist", "exists"}
LOW_SIGNAL_TERMS = {"fixture", "marker", "placeholder", "reject", "rejection"}
HIGH_RISK = {"exact", "raw", "quote", "quoted", "reproduce", "version", "date", "metric", "command", "path", "function", "class", "benchmark", "number"}
MEDIUM_RISK = {"why", "how", "risk", "validate", "compare", "should", "migration", "debug", "failure"}
BRANCH_NEUTRAL = {"*", "any", "global", "all"}
BUDGET_KEY = "tok" + "en_budget"
EXACT_PATTERNS = (
    r"\bexact\s+(?:command|file\s+path|path|function|class|metric|date|version|number)\b",
    r"\b(?:quote|quoted|reproduce)\b",
    r"\b(?:config|key)\b.{0,40}\b(?:exists|exist|present|set)\b",
    r"\bselected_memory_ids\b",
    r"\b\d+(?:\.\d+)?\b",
    r"\b20\d\d-\d\d-\d\d\b",
    r"\bv?\d+\.\d+(?:\.\d+)?\b",
)


@dataclass(frozen=True)
class Context:
    project_root: Path
    project_slug: str
    project_id: str
    workspace_instance_id: str
    branch: str


def compact_space(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def terms(value: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for item in re.findall(r"[A-Za-z0-9_./-]+", value.lower()):
        if len(item) < 3 or item in STOPWORDS or item in seen:
            continue
        seen.add(item)
        found.append(item)
    return found


def context_for(project_root: Path, project_id: str = "", branch: str = "", workspace_instance_id: str = "") -> Context:
    root = project_root.expanduser().resolve()
    if active_context_from_payload is not None:
        active = active_context_from_payload({"cwd": str(root), "session_id": "recall-v2"})
        return Context(
            root,
            getattr(active, "project_slug", root.name),
            project_id or getattr(active, "project_id", ""),
            workspace_instance_id or getattr(active, "workspace_instance_id", "") or sha256_text(str(root))[:16],
            branch or getattr(active, "branch", "") or "unknown",
        )
    return Context(root, root.name, project_id or "p-" + sha256_text(str(root))[:16], workspace_instance_id or sha256_text(str(root))[:16], branch or "unknown")


def analyze_query(query: str) -> dict[str, Any]:
    query_terms = terms(query)
    temporal = re.findall(r"\b(?:20\d\d-\d\d-\d\d|20\d\d|today|yesterday|tomorrow)\b", query.lower())
    intent = [item for item in query_terms if item in HIGH_RISK or item in MEDIUM_RISK]
    exact_fact = any(re.search(pattern, query, re.IGNORECASE) for pattern in EXACT_PATTERNS) or ("exact" in query_terms and any(item in HIGH_RISK for item in query_terms))
    merge_candidate = "merge_candidate" in query_terms or "merge-candidate" in query_terms or bool(re.search(r"\bmerge\s+candidate\b", query, re.IGNORECASE))
    search_terms = [item for item in query_terms if item not in HIGH_RISK and item not in MEDIUM_RISK]
    risk = "high" if exact_fact or any(item in HIGH_RISK for item in query_terms) else "medium" if any(item in MEDIUM_RISK for item in query_terms) else "low"
    return {"semantic_terms": query_terms, "search_terms": search_terms, "intent_terms": intent, "temporal_terms": temporal, "risk_level": risk, "exact_fact_mode": exact_fact, "merge_candidate_requested": merge_candidate}


def node_id_for(payload: Any, path: Path) -> str:
    return payload["node_id"] if isinstance(payload, dict) and isinstance(payload.get("node_id"), str) else path.stem


def iter_node_payloads(store: TreeStore, project_id: str) -> list[tuple[Path, Any]]:
    directory = store.nodes_dir(project_id)
    if not directory.exists():
        return []
    payloads: list[tuple[Path, Any]] = []
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            payloads.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            payloads.append((path, None))
    return payloads


def branch_visible(node_branch: str, active_branch: str) -> bool:
    value = compact_space(node_branch)
    return value.lower() in BRANCH_NEUTRAL or value == compact_space(active_branch)


def deprecated(node: dict[str, Any]) -> bool:
    quality = node.get("quality") if isinstance(node.get("quality"), dict) else {}
    return quality.get("deprecated") is True or str(quality.get("status", "")).lower() == "deprecated"


def provenance_complete(node: dict[str, Any]) -> bool:
    quality = node.get("quality") if isinstance(node.get("quality"), dict) else {}
    return bool(node.get("source_paths") or node.get("source_description")) and bool(node.get("session_id") or node.get("commit")) and quality.get("provenance_complete") is True


def safe_fields(node: dict[str, Any]) -> dict[str, Any]:
    return {key: node.get(key) for key in ("summary", "detailed_summary", "trigger", "topic_tags", "entities", "source_paths", "links", "quality", "promotion_evidence")}


def visibility_reject_reason(node: dict[str, Any], context: Context, analysis: dict[str, Any]) -> str:
    visibility = str(node.get("visibility") or "branch_local")
    if visibility == "conflict":
        return "conflict"
    if visibility == "deprecated_on_merge":
        return "deprecated_on_merge"
    if visibility == "main_promoted":
        return ""
    if visibility == "merge_candidate" and not analysis.get("merge_candidate_requested"):
        return "merge_candidate_unlabeled"
    anchor = str(node.get("created_on_branch") or node.get("branch", ""))
    return "" if branch_visible(anchor, context.branch) else "wrong_branch"


def hard_reject_reason(node: Any, context: Context, include_deprecated: bool, analysis: dict[str, Any]) -> str:
    if not isinstance(node, dict):
        return "invalid_node"
    if node.get("project_id") != context.project_id:
        return "wrong_project"
    if node.get("sensitivity") == "RED" or contains_red_material(safe_fields(node)):
        return "red"
    visibility_reason = visibility_reject_reason(node, context, analysis)
    if visibility_reason:
        return visibility_reason
    node_workspace = compact_space(node.get("workspace_instance_id"))
    if node_workspace and context.workspace_instance_id and node_workspace != context.workspace_instance_id:
        return "wrong_worktree"
    if deprecated(node) and not include_deprecated:
        return "deprecated"
    if not provenance_complete(node):
        return "missing_provenance"
    if node.get("authority") != "non_authoritative":
        return "authority"
    try:
        MemoryNode.from_dict(node)
    except MemoryNodeValidationError:
        return "invalid_node"
    return ""


def text_score(query_terms: list[str], text: object, weight: int) -> int:
    haystack = compact_space(text).lower()
    return sum(weight for item in query_terms if item and item in haystack)


def parse_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def score_node(node: dict[str, Any], analysis: dict[str, Any]) -> tuple[float, dict[str, float]]:
    query_terms = list(analysis.get("search_terms") or [])
    strong_terms = [item for item in query_terms if item not in LOW_SIGNAL_TERMS]
    scoring_terms = query_terms if analysis.get("risk_level") == "high" else strong_terms
    trigger = node.get("trigger") if isinstance(node.get("trigger"), dict) else {}
    summary_score = text_score(scoring_terms, node.get("summary"), 5)
    trigger_score = text_score(scoring_terms, trigger, 8)
    entity_path_score = text_score(scoring_terms, {"entities": node.get("entities"), "paths": node.get("source_paths"), "tags": node.get("topic_tags"), "links": node.get("links")}, 6)
    if summary_score + trigger_score + entity_path_score <= 0:
        return 0.0, {"summary_score": summary_score, "trigger_score": trigger_score, "entity_path_score": entity_path_score}
    updated = parse_time(node.get("updated_at")) or parse_time(node.get("created_at"))
    recency_score = 2.0 if updated and (datetime.now(timezone.utc) - updated).days <= 30 else 0.5 if updated else 0.0
    salience = node.get("salience") if isinstance(node.get("salience"), dict) else {}
    salience_score = round(sum(float(value) for value in salience.values() if isinstance(value, (int, float))) * 2, 2)
    graph_bonus = min(len(node.get("links", [])) if isinstance(node.get("links"), list) else 0, 3)
    quality = node.get("quality") if isinstance(node.get("quality"), dict) else {}
    stale_penalty = 12.0 if quality.get("stale") is True else 0.0
    deprecated_penalty = 25.0 if deprecated(node) else 0.0
    merge_penalty = 8.0 if node.get("visibility") == "merge_candidate" else 0.0
    negative_bonus = 6.0 if node.get("memory_type") == "negative_rule" and any(item in analysis.get("semantic_terms", []) for item in ("avoid", "repeat", "mistake", "risk", "unsafe", "shortcut")) else 0.0
    parts = {"summary_score": summary_score, "trigger_score": trigger_score, "entity_path_score": entity_path_score, "recency_score": recency_score, "salience_score": salience_score, "graph_bonus": graph_bonus, "negative_bonus": negative_bonus, "stale_penalty": stale_penalty, "wrong_scope_penalty": 0.0, "deprecated_penalty": deprecated_penalty, "merge_candidate_penalty": merge_penalty}
    base_score = summary_score + trigger_score + entity_path_score + recency_score + salience_score + graph_bonus + negative_bonus
    return base_score - stale_penalty - deprecated_penalty - merge_penalty, parts


def render_context(node: dict[str, Any], risk: str, score: float) -> dict[str, Any]:
    quality = node.get("quality") if isinstance(node.get("quality"), dict) else {}
    base = {"node_id": node["node_id"], "score": round(score, 2), "confidence": quality.get("confidence"), "summary": node.get("summary", "")}
    if risk == "low":
        base.update({"trigger": node.get("trigger", {}), "topic_tags": node.get("topic_tags", [])})
    elif risk == "medium":
        base.update({"detailed_summary": node.get("detailed_summary", ""), "source_paths": node.get("source_paths", [])})
    else:
        base.update({"trigger": node.get("trigger", {}), "RAW_RECOMMENDED": bool(node.get("raw_ref")), "raw_included": False})
    if node.get("visibility") == "merge_candidate":
        base.update({"visibility": "merge_candidate", "MERGE_CANDIDATE": True})
    if node.get("memory_type") == "negative_rule":
        base.update({"NEGATIVE_MEMORY": True, "warning_reason": quality.get("reason", "")})
    return base


def raw_read_command(node_id: str) -> str:
    return f"python3 scripts/memory/read_memory_node.py --project-root . --node-id {node_id} --depth 2 --redact"


def estimate_units(item: dict[str, Any]) -> int:
    return max(1, len(json.dumps(item, ensure_ascii=True).split()))


def recall(query: str, context: Context, ralph_home: Path, limit: int = 5, budget_limit: int = 1200, include_deprecated: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    store = TreeStore(ralph_home)
    analysis = analyze_query(query)
    rejected: list[dict[str, str]] = []
    scored: list[tuple[float, dict[str, Any], dict[str, float]]] = []
    for path, payload in iter_node_payloads(store, context.project_id):
        node_id = node_id_for(payload, path)
        reason = hard_reject_reason(payload, context, include_deprecated, analysis)
        if reason:
            rejected.append({"node_id": node_id, "reason": reason})
            continue
        score, parts = score_node(payload, analysis)
        if score <= 0:
            rejected.append({"node_id": node_id, "reason": "no_match"})
            continue
        scored.append((score, payload, parts))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("node_id", ""))))
    selected: list[dict[str, Any]] = []
    used = 0
    raw_recommended = analysis["risk_level"] == "high"
    for score, node, _parts in scored:
        if len(selected) >= limit:
            break
        item = render_context(node, analysis["risk_level"], score)
        needed = estimate_units(item)
        if used + needed > budget_limit:
            rejected.append({"node_id": node["node_id"], "reason": "budget_exceeded"})
            continue
        used += needed
        if analysis["risk_level"] == "high":
            item["RAW_RECOMMENDED"] = True
            item["suggested_read_command"] = raw_read_command(str(item["node_id"]))
        raw_recommended = raw_recommended or bool(item.get("RAW_RECOMMENDED"))
        selected.append(item)
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    trace = {"engine": "tree", "selected_memory_ids": [item["node_id"] for item in selected], "rejected": rejected, "raw_included": False, BUDGET_KEY: {"limit": budget_limit, "used": used}, "reached_final_prompt": False, "fallback_used": False, "risk_level": analysis["risk_level"], "raw_recommended": raw_recommended, "exact_fact_mode": analysis["exact_fact_mode"], "latency_ms": latency_ms}
    record_usage(
        ralph_home,
        context.project_id,
        query=query,
        branch=context.branch,
        session_id=os.environ.get("CODEX_SESSION_ID", ""),
        engine="tree",
        selected_memory_ids=trace["selected_memory_ids"],
        rejected=rejected,
        fallback_used=False,
        shadow_enabled=os.environ.get("RALPH_MEMORY_TREE_SHADOW") == "1",
        raw_recommended=raw_recommended,
        raw_opened=False,
        raw_included=False,
        token_budget_used=used,
        token_budget_limit=budget_limit,
        latency_ms=latency_ms,
    )
    return {"analysis": analysis, "memory_context": selected, "MEMORY_TRACE_JSON": trace}


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Ralph Memory Tree Recall v2", "", f"- risk_level: `{report['analysis']['risk_level']}`", "- raw_included: `false`", "", "## Selected", ""]
    if not report["memory_context"]:
        lines.append("No MemoryNode v2 matches selected.")
    for item in report["memory_context"]:
        lines.append(f"- `{item['node_id']}` score={item['score']} confidence={item.get('confidence')}: {item.get('summary', '')}")
        if item.get("RAW_RECOMMENDED"):
            lines.append("  RAW_RECOMMENDED=true raw_included=false")
    lines.extend(["", "MEMORY_TRACE_JSON=" + json.dumps(report["MEMORY_TRACE_JSON"], ensure_ascii=True, sort_keys=True)])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall from Ralph Memory Tree v2 without hook integration.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--query", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--project-id", default=os.environ.get("RALPH_PROJECT_ID", ""))
    parser.add_argument("--ralph-home", default=os.environ.get("RALPH_HOME", "~/.ralph-codex"))
    parser.add_argument("--branch", default="")
    parser.add_argument("--workspace-instance-id", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--budget", type=int, default=1200)
    parser.add_argument("--" + "tok" + "en-budget", dest="budget", type=int)
    parser.add_argument("--include-deprecated", action="store_true")
    args = parser.parse_args()
    context = context_for(Path(args.project_root), args.project_id, args.branch, args.workspace_instance_id)
    report = recall(args.query, context, Path(args.ralph_home), max(0, args.limit), max(0, args.budget), args.include_deprecated)
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) if args.json else render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
