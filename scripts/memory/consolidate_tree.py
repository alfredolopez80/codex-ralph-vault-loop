#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from memory_node import MemoryNode, MemoryNodeValidationError, contains_red_material, sha256_text  # noqa: E402
from recall_v2 import context_for  # noqa: E402
from tree_store import TreeStore  # noqa: E402

LINK_RELATIONS = {"supports", "contradicts", "updates", "supersedes", "same_topic", "depends_on"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def word_set(value: object) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9_./-]{3,}", norm(value))}


def trigger_terms(node: dict[str, Any]) -> set[str]:
    trigger = node.get("trigger") if isinstance(node.get("trigger"), dict) else {}
    return word_set(trigger.get("terms", [])) | word_set(trigger.get("paths", []))


def node_id(payload: Any, path: Path) -> str:
    return payload.get("node_id", path.stem) if isinstance(payload, dict) else path.stem


def raw_payloads(store: TreeStore, project_id: str) -> list[tuple[Path, Any]]:
    directory = store.nodes_dir(project_id)
    if not directory.exists():
        return []
    output: list[tuple[Path, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            output.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            output.append((path, None))
    return output


def visible_for_consolidation(node: dict[str, Any], branch: str | None) -> bool:
    if branch is None:
        return True
    visibility = str(node.get("visibility") or "branch_local")
    if visibility == "main_promoted":
        return True
    if visibility in {"conflict", "deprecated_on_merge"}:
        return False
    anchor = str(node.get("created_on_branch") or node.get("branch") or "")
    return anchor == branch


def safe_nodes(store: TreeStore, project_id: str, branch: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    nodes: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for path, payload in raw_payloads(store, project_id):
        nid = node_id(payload, path)
        if not isinstance(payload, dict):
            skipped.append({"node_id": nid, "reason": "invalid_node"})
            continue
        if payload.get("sensitivity") == "RED" or contains_red_material(payload):
            skipped.append({"node_id": nid, "reason": "red"})
            continue
        try:
            node = MemoryNode.from_dict(payload).to_dict()
        except MemoryNodeValidationError:
            skipped.append({"node_id": nid, "reason": "invalid_node"})
            continue
        if not visible_for_consolidation(node, branch):
            skipped.append({"node_id": nid, "reason": "wrong_branch_scope"})
            continue
        nodes.append(node)
    return nodes, skipped


def overlap(left: set[str], right: set[str]) -> bool:
    return bool(left and right and left & right)


def duplicate_ops(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    for index, left in enumerate(nodes):
        for right in nodes[index + 1 :]:
            same_summary = norm(left.get("summary")) == norm(right.get("summary"))
            shared_trigger = overlap(trigger_terms(left), trigger_terms(right))
            shared_source = overlap(set(left.get("source_paths", [])), set(right.get("source_paths", [])))
            shared_entity = overlap(set(left.get("entities", [])), set(right.get("entities", [])))
            if same_summary or (shared_trigger and (shared_source or shared_entity)):
                canonical, duplicate = sorted([left, right], key=lambda item: str(item["node_id"]))
                ops.append({"canonical": canonical["node_id"], "duplicate": duplicate["node_id"], "reason": "duplicate_overlap"})
    return dedupe_ops(ops, ("canonical", "duplicate"))


def link_target(link: dict[str, Any]) -> str:
    return str(link.get("target_node_id", link.get("node_id", "")))


def link_exists(node: dict[str, Any], relation: str, target: str) -> bool:
    return any(isinstance(item, dict) and item.get("relation") == relation and link_target(item) == target for item in node.get("links", []))


def dedupe_ops(ops: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    output: list[dict[str, Any]] = []
    for op in ops:
        key = tuple(str(op[item]) for item in keys)
        if key not in seen:
            seen.add(key)
            output.append(op)
    return output


def hinted_links(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {node["node_id"]: node for node in nodes}
    ops: list[dict[str, Any]] = []
    for node in nodes:
        quality = node.get("quality") if isinstance(node.get("quality"), dict) else {}
        for target in quality.get("supersedes_node_ids", []):
            if target in by_id:
                ops.append({"source": node["node_id"], "target": target, "relation": "supersedes", "evidence": "quality.supersedes_node_ids"})
        for link in node.get("links", []):
            if isinstance(link, dict) and link.get("relation") == "supersedes" and link_target(link) in by_id:
                ops.append({"source": node["node_id"], "target": link_target(link), "relation": "supersedes", "evidence": "existing_supersedes_link"})
        for hint in quality.get("link_hints", []):
            relation, target = str(hint.get("relation", "")), str(hint.get("target_node_id", hint.get("node_id", "")))
            if relation in LINK_RELATIONS and target in by_id:
                ops.append({"source": node["node_id"], "target": target, "relation": relation, "evidence": "quality.link_hints"})
    return dedupe_ops(ops, ("source", "target", "relation"))


def same_topic_links(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    for index, left in enumerate(nodes):
        for right in nodes[index + 1 :]:
            shared = sorted(set(left.get("topic_tags", [])) & set(right.get("topic_tags", [])))
            if shared and not link_exists(left, "same_topic", right["node_id"]):
                ops.append({"source": left["node_id"], "target": right["node_id"], "relation": "same_topic", "evidence": "topic_tags"})
    return ops


def hub_nodes(nodes: list[dict[str, Any]], project_id: str, branch: str) -> list[dict[str, Any]]:
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        for topic in node.get("topic_tags", []):
            by_topic.setdefault(str(topic), []).append(node)
    existing = {node["node_id"] for node in nodes}
    hubs: list[dict[str, Any]] = []
    for topic, members in sorted(by_topic.items()):
        if len(members) < 2:
            continue
        hub_id = "hub_" + sha256_text(f"{project_id}:{topic}")[:24]
        if hub_id in existing:
            continue
        hubs.append(
            {
                "schema_version": "ralph_memory_node_v2",
                "node_id": hub_id,
                "project_id": project_id,
                "workspace_instance_id": members[0].get("workspace_instance_id", ""),
                "repo_remote_hash": members[0].get("repo_remote_hash", ""),
                "branch": branch or members[0].get("branch", ""),
                "created_on_branch": branch or members[0].get("created_on_branch", members[0].get("branch", "")),
                "visibility": "branch_local",
                "promotion_status": "not_promoted",
                "promotion_evidence": {"synthetic": True, "source_node_ids": [node["node_id"] for node in members]},
                "commit": members[0].get("commit", ""),
                "session_id": "consolidation",
                "memory_type": "hub",
                "sensitivity": "YELLOW",
                "authority": "non_authoritative",
                "summary": f"Synthetic hub for topic {topic}.",
                "detailed_summary": f"Synthetic hub linking {len(members)} safe summary nodes for topic {topic}.",
                "trigger": {"terms": [topic]},
                "topic_tags": [topic],
                "entities": [],
                "source_paths": [],
                "source_description": "Synthetic consolidation hub from safe MemoryNode summaries.",
                "raw_ref": None,
                "links": [{"relation": "same_topic", "target_node_id": node["node_id"], "evidence": "hub_member"} for node in members],
                "salience": {"validation": 0.3},
                "quality": {"confidence": 0.7, "provenance_complete": True, "validation_status": "pass", "synthetic": True},
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "compaction_reason": "synthetic_consolidation_hub",
            }
        )
    return hubs


def build_plan(store: TreeStore, project_id: str, branch: str, explain: bool = False) -> dict[str, Any]:
    nodes, skipped = safe_nodes(store, project_id, branch)
    links = dedupe_ops([*hinted_links(nodes), *same_topic_links(nodes)], ("source", "target", "relation"))
    supersessions = [item for item in links if item["relation"] == "supersedes"]
    duplicates = duplicate_ops(nodes)
    hubs = hub_nodes(nodes, project_id, branch)
    report: dict[str, Any] = {"dry_run": True, "project_id": project_id, "nodes_considered": len(nodes), "skipped": skipped, "duplicates": duplicates, "supersessions": supersessions, "links": links, "virtual_hubs": [{"node_id": hub["node_id"], "topic_tags": hub["topic_tags"], "raw_ref": None} for hub in hubs], "snapshot_id": None, "written": [], "restored_from_snapshot": False}
    if explain:
        report["explain"] = [{"op": "mark_duplicate", **item} for item in duplicates] + [{"op": "link", **item} for item in links] + [{"op": "create_hub", "node_id": hub["node_id"], "summary_hash": sha256_text(hub["summary"])[:16]} for hub in hubs]
    report["_hub_payloads"] = hubs
    return report


def add_link(node: dict[str, Any], relation: str, target: str, evidence: str) -> list[dict[str, Any]]:
    links = [item for item in node.get("links", []) if isinstance(item, dict)]
    if not any(item.get("relation") == relation and link_target(item) == target for item in links):
        links.append({"relation": relation, "target_node_id": target, "evidence": evidence})
    return links


def apply_plan(store: TreeStore, report: dict[str, Any]) -> dict[str, Any]:
    project_id = str(report["project_id"])
    report["dry_run"] = False
    mutating = bool(report["duplicates"] or report["links"] or report["_hub_payloads"])
    if not mutating:
        report.pop("_hub_payloads", None)
        return report
    report["snapshot_id"] = store.snapshot_tree(project_id, "consolidation_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    try:
        for item in report["duplicates"]:
            duplicate = store.load_node(project_id, item["duplicate"])
            quality = dict(duplicate.get("quality", {}))
            quality.update({"duplicate_of": item["canonical"], "deprecated": True, "status": "duplicate"})
            store.update_node(project_id, item["duplicate"], {"quality": quality})
            report["written"].append({"node_id": item["duplicate"], "op": "mark_duplicate"})
        for item in report["supersessions"]:
            old = store.load_node(project_id, item["target"])
            quality = dict(old.get("quality", {}))
            quality.update({"deprecated": True, "stale": True, "status": "deprecated"})
            store.update_node(project_id, item["target"], {"quality": quality})
            report["written"].append({"node_id": item["target"], "op": "superseded"})
        for item in report["links"]:
            source = store.load_node(project_id, item["source"])
            links = add_link(source, item["relation"], item["target"], item["evidence"])
            store.update_node(project_id, item["source"], {"links": links})
            report["written"].append({"node_id": item["source"], "op": "link", "relation": item["relation"]})
        for hub in report["_hub_payloads"]:
            store.create_node(hub)
            report["written"].append({"node_id": hub["node_id"], "op": "create_hub"})
    except Exception as exc:
        report["error"] = "write_failed"
        report["error_type"] = exc.__class__.__name__
        report["written"] = []
        try:
            store.restore_snapshot(project_id, str(report["snapshot_id"]))
            report["restored_from_snapshot"] = True
        except Exception as restore_exc:  # pragma: no cover
            report["restore_error_type"] = restore_exc.__class__.__name__
    report.pop("_hub_payloads", None)
    return report


def consolidate_tree(store: TreeStore, project_id: str, branch: str, write: bool = False, explain: bool = False) -> dict[str, Any]:
    report = build_plan(store, project_id, branch, explain)
    return apply_plan(store, report) if write else {key: value for key, value in report.items() if key != "_hub_payloads"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely consolidate Ralph Memory Tree v2 nodes.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--project-id", default=os.environ.get("RALPH_MEMORY_PROJECT_ID", ""))
    parser.add_argument("--ralph-home", default=os.environ.get("RALPH_HOME", "~/.ralph-codex"))
    parser.add_argument("--branch", default="")
    parser.add_argument("--explain", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    context = context_for(Path(args.project_root), args.project_id, args.branch)
    report = consolidate_tree(TreeStore(Path(args.ralph_home)), context.project_id, context.branch, write=args.write, explain=args.explain)
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 1 if report.get("error") and args.write else 0


if __name__ == "__main__":
    raise SystemExit(main())
