#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
for import_dir in (SCRIPT_DIR, REPO_ROOT / "scripts" / "security"):
    if str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))

from recall_v2 import context_for, hard_reject_reason  # noqa: E402
from sensitive_content import redact_text  # noqa: E402
from tree_store import TreeStore, TreeStorePathError  # noqa: E402


def confidence(node: dict[str, Any]) -> object:
    quality = node.get("quality") if isinstance(node.get("quality"), dict) else {}
    return quality.get("confidence")


def depth_zero(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node["node_id"],
        "depth": 0,
        "summary": node.get("summary", ""),
        "trigger": node.get("trigger", {}),
        "topic_tags": node.get("topic_tags", []),
        "confidence": confidence(node),
        "raw_included": False,
    }


def depth_one(node: dict[str, Any]) -> dict[str, Any]:
    payload = depth_zero(node)
    payload.update(
        {
            "depth": 1,
            "detailed_summary": node.get("detailed_summary", ""),
            "source_paths": node.get("source_paths", []),
        }
    )
    return payload


def depth_two(store: TreeStore, project_id: str, node: dict[str, Any], redact: bool) -> tuple[int, dict[str, Any]]:
    if not redact:
        return 2, {"error": "depth_2_requires_redact", "node_id": node.get("node_id"), "raw_included": False}
    raw_ref = node.get("raw_ref") if isinstance(node.get("raw_ref"), dict) else {}
    digest = raw_ref.get("sha256")
    if not digest:
        return 2, {"error": "raw_ref_missing", "node_id": node.get("node_id"), "raw_included": False}
    raw = store.read_raw(project_id, str(digest))
    if raw is None:
        return 2, {"error": "raw_unavailable_or_unsafe", "node_id": node.get("node_id"), "raw_included": False}
    redacted, changed = redact_text(raw)
    return 0, {"node_id": node["node_id"], "depth": 2, "raw_redacted": redacted, "redaction_changed": changed, "raw_included": True}


def read_node(project_root: Path, ralph_home: Path, project_id: str, node_id: str, depth: int, redact: bool, branch: str = "", workspace_instance_id: str = "") -> tuple[int, dict[str, Any]]:
    context = context_for(project_root, project_id, branch, workspace_instance_id)
    store = TreeStore(ralph_home)
    try:
        node = store.load_node(context.project_id, node_id)
    except TreeStorePathError:
        return 2, {"error": "invalid_node_id", "node_id": node_id, "raw_included": False}
    if node is None:
        return 1, {"error": "node_not_found", "node_id": node_id, "raw_included": False}
    reason = hard_reject_reason(node, context, include_deprecated=False, analysis={"merge_candidate_requested": True})
    if reason:
        return 1, {"error": reason, "node_id": node_id, "raw_included": False}
    if depth == 0:
        return 0, depth_zero(node)
    if depth == 1:
        return 0, depth_one(node)
    if depth == 2:
        return depth_two(store, context.project_id, node, redact)
    return 2, {"error": "unsupported_depth", "node_id": node_id, "raw_included": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a MemoryNode v2 at an explicit retrieval depth.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--depth", type=int, choices=(0, 1, 2), required=True)
    parser.add_argument("--redact", action="store_true")
    parser.add_argument("--project-id", default=os.environ.get("RALPH_PROJECT_ID", ""))
    parser.add_argument("--ralph-home", default=os.environ.get("RALPH_HOME", "~/.ralph-codex"))
    parser.add_argument("--branch", default="")
    parser.add_argument("--workspace-instance-id", default="")
    args = parser.parse_args()
    code, payload = read_node(Path(args.project_root), Path(args.ralph_home), args.project_id, args.node_id, args.depth, args.redact, args.branch, args.workspace_instance_id)
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
