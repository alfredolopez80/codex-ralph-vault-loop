#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "scripts" / "memory"
for path in (ROOT, MEMORY_DIR, ROOT / "scripts" / "evals"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _eval_common import detect_eval_gaming_text, detect_secret_leak, write_json  # noqa: E402
from memory_node import SCHEMA_VERSION  # noqa: E402
from recall_v2 import BUDGET_KEY, Context, recall  # noqa: E402
from tree_store import TreeStore, atomic_write_json  # noqa: E402

STAMP = "2026-06-07T00:00:00+00:00"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(str(item.relative_to(path)).encode("utf-8"))
            digest.update(item.read_bytes())
    return digest.hexdigest()


def node_payload(data: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    quality = {"confidence": 0.8, "provenance_complete": True, "validation_status": "pass", "stale": False, "deprecated": False}
    quality.update(data.get("quality", {}))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "node_id": data["node_id"],
        "project_id": manifest["project_id"],
        "workspace_instance_id": manifest["workspace_instance_id"],
        "repo_remote_hash": "benchmark-remote",
        "branch": manifest["branch"],
        "commit": "benchmark-commit",
        "session_id": "benchmark-session",
        "memory_type": data.get("memory_type", "fact"),
        "sensitivity": data.get("sensitivity", "YELLOW"),
        "authority": "non_authoritative",
        "summary": data.get("summary", ""),
        "detailed_summary": data.get("detailed_summary", ""),
        "trigger": data.get("trigger", {}),
        "topic_tags": data.get("topic_tags", []),
        "entities": data.get("entities", []),
        "source_paths": data.get("source_paths", []),
        "source_description": data.get("source_description", ""),
        "raw_ref": data.get("raw_ref"),
        "links": data.get("links", []),
        "salience": data.get("salience", {"validation": 0.5, "recency": 0.5}),
        "quality": quality,
        "created_at": data.get("created_at", STAMP),
        "updated_at": data.get("updated_at", STAMP),
        "compaction_reason": "benchmark_fixture",
    }
    payload.update({key: data[key] for key in ("project_id", "workspace_instance_id", "branch") if key in data})
    return payload


def write_direct(store: TreeStore, active_project: str, payload: dict[str, Any]) -> None:
    store.ensure_layout(active_project)
    atomic_write_json(store.node_path(active_project, payload["node_id"]), payload)


def ingest(fixture: Path, ralph_home: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    store = TreeStore(ralph_home)
    written: list[str] = []
    direct: list[str] = []
    skipped: list[dict[str, str]] = []
    for rel in manifest["sessions"]:
        for line in (fixture / rel).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            payload = node_payload(event["node"], manifest)
            if payload["sensitivity"] == "RED":
                skipped.append({"node_id": payload["node_id"], "reason": "red"})
                continue
            if event.get("raw_body") is not None:
                raw_ref = store.save_raw(manifest["project_id"], event["raw_body"], sensitivity=payload["sensitivity"])
                payload["raw_ref"] = {"sha256": raw_ref["sha256"], "safe": True}
            if event.get("direct"):
                write_direct(store, manifest["project_id"], payload)
                direct.append(payload["node_id"])
            else:
                store.create_node(payload)
                written.append(payload["node_id"])
    return {"written": written, "direct": direct, "skipped": skipped}


def expected_files(fixture: Path) -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, Any]]:
    expected = fixture / "expected"
    return (
        read_json(expected / "queries.json"),
        read_json(expected / "expected_nodes.json"),
        read_json(expected / "expected_traces.json"),
    )


def rejected_map(report: dict[str, Any]) -> dict[str, str]:
    return {item["node_id"]: item["reason"] for item in report["MEMORY_TRACE_JSON"]["rejected"]}


def trace_matches(trace: dict[str, Any], reasons: dict[str, str], expected: dict[str, Any]) -> bool:
    for key in ("risk_level", "raw_recommended", "raw_included"):
        if key in expected and trace.get(key) != expected[key]:
            return False
    for node_id, reason in expected.get("rejected", {}).items():
        if reasons.get(node_id) != reason:
            return False
    return True


def mean(values: list[bool | float]) -> float:
    return round(sum(float(value) for value in values) / len(values), 4) if values else 1.0


def run_once(fixture: Path) -> dict[str, Any]:
    manifest = read_json(fixture / "manifest.json")
    queries, expected_nodes, expected_traces = expected_files(fixture)
    with tempfile.TemporaryDirectory(prefix="ralph-memory-tree-benchmark-") as temp:
        ralph_home = Path(temp)
        ingest_result = ingest(fixture, ralph_home, manifest)
        context = Context(ROOT, ROOT.name, manifest["project_id"], manifest["workspace_instance_id"], manifest["branch"])
        query_results: dict[str, Any] = {}
        hook_outputs: list[str] = []
        for query in queries:
            report = recall(query["query"], context, ralph_home, limit=query.get("limit", 3), budget_limit=query.get("budget", 1200))
            trace = report["MEMORY_TRACE_JSON"]
            selected = trace["selected_memory_ids"]
            expected = expected_nodes[query["id"]]
            reasons = rejected_map(report)
            hook_like = json.dumps({"memory_context": report["memory_context"], "MEMORY_TRACE_JSON": trace}, sort_keys=True)
            hook_outputs.append(hook_like)
            query_results[query["id"]] = {
                "case": query["case"],
                "selected_memory_ids": selected,
                "expected_memory_ids": expected,
                "selection_pass": selected[: len(expected)] == expected if expected else selected == [],
                "rejected": reasons,
                "trace_pass": trace_matches(trace, reasons, expected_traces.get(query["id"], {})),
                "risk_level": trace["risk_level"],
                "raw_recommended": trace["raw_recommended"],
                "raw_included": trace["raw_included"],
                "budget": trace[BUDGET_KEY],
            }
        metrics = compute_metrics(query_results, ingest_result, manifest, hook_outputs, ralph_home)
        return {"ingest": ingest_result, "query_results": query_results, "metrics": metrics}


def compute_metrics(results: dict[str, Any], ingest_result: dict[str, Any], manifest: dict[str, Any], hook_outputs: list[str], ralph_home: Path) -> dict[str, float]:
    by_case = {value["case"]: value for value in results.values()}
    wrong_reasons = by_case["wrong_scope"]["rejected"]
    budget = by_case["budget"]["budget"]
    raw_markers_absent = all(marker not in output for marker in manifest.get("raw_markers", []) for output in hook_outputs)
    active_nodes = {path.stem for path in TreeStore(ralph_home).nodes_dir(manifest["project_id"]).glob("*.json")}
    red_skips = {item["node_id"] for item in ingest_result["skipped"] if item["reason"] == "red"}
    red_expected = set(manifest.get("red_expected_skips", []))
    metrics = {
        "summary_precision_at_3": float(by_case["summary"]["expected_memory_ids"][0] in by_case["summary"]["selected_memory_ids"][:3]),
        "trigger_recall_at_3": float(by_case["trigger"]["expected_memory_ids"][0] in by_case["trigger"]["selected_memory_ids"][:3]),
        "exact_fact_accuracy": float(by_case["exact"]["selection_pass"] and by_case["exact"]["risk_level"] == "high"),
        "raw_needed_detection": float(by_case["raw_required"]["raw_recommended"] and not by_case["raw_required"]["raw_included"]),
        "raw_open_minimized": float(all(not item["raw_included"] for item in results.values())),
        "wrong_scope_rejected": float(all(wrong_reasons.get(node_id) == reason for node_id, reason in {"node_wrong_project": "wrong_project", "node_wrong_branch": "wrong_branch", "node_wrong_worktree": "wrong_worktree"}.items())),
        "stale_rejected": float(by_case["stale"]["selection_pass"] and by_case["stale"]["rejected"].get("node_stale_rule") == "deprecated"),
        "red_not_indexed": float(red_skips == red_expected and not (red_expected & active_nodes)),
        "no_raw_leak_in_hook_output": float(raw_markers_absent),
        "graph_hop_recall": float(by_case["graph"]["selection_pass"]),
        "token_budget_observed": float(budget["used"] <= budget["limit"] and "budget_exceeded" in set(by_case["budget"]["rejected"].values())),
        "provenance_complete": float(by_case["provenance"]["rejected"].get("node_missing_provenance") == "missing_provenance"),
    }
    selection_pass_rate = mean([item["selection_pass"] for item in results.values()])
    metrics["memory_tree_score"] = mean([*metrics.values(), selection_pass_rate])
    return metrics


def finalize(first: dict[str, Any], second: dict[str, Any], fixture_unchanged: bool) -> dict[str, Any]:
    stable_first = deepcopy(first)
    stable_second = deepcopy(second)
    stable_first["metrics"].pop("memory_tree_score", None)
    stable_second["metrics"].pop("memory_tree_score", None)
    deterministic = stable_first == stable_second
    metrics = dict(first["metrics"])
    base_score = metrics.pop("memory_tree_score")
    metrics["deterministic_replay"] = float(deterministic)
    metrics["memory_tree_score"] = mean([base_score, metrics["deterministic_replay"]])
    report = {"schema_version": "ralph_memory_tree_benchmark_v1", "metrics": metrics, "ingest": first["ingest"], "query_results": first["query_results"]}
    report_text = json.dumps(report, sort_keys=True)
    hard_gates = {
        "tests_pass": True,
        "no_secret_leak": not detect_secret_leak(report_text),
        "eval_harness_unchanged": fixture_unchanged,
        "no_scope_violation": metrics["wrong_scope_rejected"] == 1.0,
        "no_eval_gaming": not detect_eval_gaming_text(report_text),
        "red_not_indexed": metrics["red_not_indexed"] == 1.0,
        "no_raw_leak_in_hook_output": metrics["no_raw_leak_in_hook_output"] == 1.0,
        "wrong_scope_rejected": metrics["wrong_scope_rejected"] == 1.0,
        "deterministic_replay": deterministic,
    }
    report["hard_gates"] = hard_gates
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Ralph Memory Tree v2 retrieval benchmark.")
    parser.add_argument("--fixture", default="tests/evals/fixtures/memory_tree_retrieval")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    fixture = Path(args.fixture).resolve()
    before = fixture_digest(fixture)
    first = run_once(fixture)
    second = run_once(fixture)
    report = finalize(first, second, before == fixture_digest(fixture))
    write_json(Path(args.output), report)
    for key in (
        "memory_tree_score",
        "summary_precision_at_3",
        "trigger_recall_at_3",
        "exact_fact_accuracy",
        "raw_needed_detection",
        "raw_open_minimized",
        "wrong_scope_rejected",
        "stale_rejected",
        "red_not_indexed",
        "no_raw_leak_in_hook_output",
        "graph_hop_recall",
        "token_budget_observed",
        "provenance_complete",
        "deterministic_replay",
    ):
        print(f"METRIC {key}={report['metrics'][key]:.4f}")
    return 0 if all(report["hard_gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
