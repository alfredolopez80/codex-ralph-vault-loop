#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from memory_node import contains_red_material  # noqa: E402
from recall_v2 import context_for, provenance_complete  # noqa: E402
from tree_store import TreeStore  # noqa: E402


def compact(value: object) -> str:
    return " ".join(str(value or "").split())


def normalized_summary(node: dict[str, Any]) -> str:
    return compact(node.get("summary")).lower()


def candidate_branch(node: dict[str, Any]) -> str:
    return compact(node.get("created_on_branch") or node.get("branch"))


def safe_payload(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": node.get("summary"),
        "detailed_summary": node.get("detailed_summary"),
        "trigger": node.get("trigger"),
        "topic_tags": node.get("topic_tags"),
        "entities": node.get("entities"),
        "source_paths": node.get("source_paths"),
        "source_description": node.get("source_description"),
        "promotion_evidence": node.get("promotion_evidence"),
    }


def evidence_reasons(node: dict[str, Any]) -> list[str]:
    evidence = node.get("promotion_evidence") if isinstance(node.get("promotion_evidence"), dict) else {}
    reasons: list[str] = []
    if evidence.get("tests_passed") is not True and not evidence.get("tests"):
        reasons.append("missing_tests_evidence")
    if evidence.get("gates_passed") is not True and not evidence.get("gates"):
        reasons.append("missing_gates_evidence")
    return reasons


def conflicts_with_main(candidate: dict[str, Any], promoted: list[dict[str, Any]]) -> bool:
    candidate_paths = {str(item) for item in candidate.get("source_paths") or []}
    candidate_tags = {str(item).lower() for item in candidate.get("topic_tags") or []}
    for current in promoted:
        if normalized_summary(candidate) == normalized_summary(current):
            continue
        current_paths = {str(item) for item in current.get("source_paths") or []}
        current_tags = {str(item).lower() for item in current.get("topic_tags") or []}
        if candidate_paths & current_paths:
            return True
        if candidate.get("memory_type") == current.get("memory_type") and candidate_tags & current_tags:
            return True
    return False


def promotion_skip_reasons(node: dict[str, Any], source_branch: str, main_nodes: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    if node.get("visibility") != "merge_candidate":
        reasons.append("not_merge_candidate")
    if candidate_branch(node) != compact(source_branch):
        reasons.append("wrong_source_branch")
    if not provenance_complete(node):
        reasons.append("missing_provenance")
    reasons.extend(evidence_reasons(node))
    if contains_red_material(safe_payload(node)):
        reasons.append("unsafe_content")
    if conflicts_with_main(node, main_nodes):
        reasons.append("conflicts_with_main_promoted")
    return reasons


def snapshot_id() -> str:
    return "promotion_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def promoted_evidence(node: dict[str, Any], source_branch: str, target_branch: str) -> dict[str, Any]:
    evidence = dict(node.get("promotion_evidence") if isinstance(node.get("promotion_evidence"), dict) else {})
    evidence.update(
        {
            "promoted_from_branch": source_branch,
            "promoted_to_branch": target_branch,
            "promoted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
    )
    return evidence


def promote_branch_memory(
    store: TreeStore,
    project_id: str,
    source_branch: str,
    target_branch: str = "main",
    write: bool = False,
) -> dict[str, Any]:
    nodes = store.list_nodes(project_id)
    main_nodes = [node for node in nodes if node.get("visibility") == "main_promoted"]
    report: dict[str, Any] = {
        "dry_run": not write,
        "project_id": project_id,
        "source_branch": source_branch,
        "target_branch": target_branch,
        "snapshot_id": None,
        "candidates": [],
        "promoted": [],
        "skipped": [],
        "restored_from_snapshot": False,
    }
    eligible: list[dict[str, Any]] = []
    for node in nodes:
        reasons = promotion_skip_reasons(node, source_branch, main_nodes)
        item = {"node_id": node.get("node_id", ""), "visibility": node.get("visibility", "branch_local")}
        if reasons:
            report["skipped"].append({**item, "reasons": reasons})
            continue
        report["candidates"].append(item)
        eligible.append(node)
    if not write or not eligible:
        return report
    report["snapshot_id"] = store.snapshot_tree(project_id, snapshot_id())
    try:
        for node in eligible:
            evidence = promoted_evidence(node, source_branch, target_branch)
            store.update_node(
                project_id,
                str(node["node_id"]),
                {
                    "branch": target_branch,
                    "visibility": "main_promoted",
                    "promotion_status": "promoted",
                    "promotion_evidence": evidence,
                },
            )
            report["promoted"].append({"node_id": node["node_id"], "visibility": "main_promoted"})
    except Exception as exc:  # pragma: no cover - exercised through monkeypatch.
        report["promoted"] = []
        report["error"] = "write_failed"
        report["error_type"] = exc.__class__.__name__
        try:
            store.restore_snapshot(project_id, str(report["snapshot_id"]))
            report["restored_from_snapshot"] = True
        except Exception as restore_exc:  # pragma: no cover
            report["restore_error_type"] = restore_exc.__class__.__name__
        return report
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote Ralph Memory Tree branch candidates after evidence checks.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--project-id", default=os.environ.get("RALPH_PROJECT_ID", ""))
    parser.add_argument("--ralph-home", default=os.environ.get("RALPH_HOME", "~/.ralph-codex"))
    parser.add_argument("--source-branch", default="")
    parser.add_argument("--target-branch", default="main")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    context = context_for(Path(args.project_root), args.project_id, args.source_branch)
    report = promote_branch_memory(
        TreeStore(Path(args.ralph_home)),
        context.project_id,
        args.source_branch or context.branch,
        args.target_branch,
        write=args.write,
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 1 if report.get("error") and args.write else 0


if __name__ == "__main__":
    raise SystemExit(main())
