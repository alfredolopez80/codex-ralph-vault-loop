#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
for import_dir in (SCRIPT_DIR, REPO_ROOT / ".codex" / "hooks", REPO_ROOT / "scripts" / "security"):
    if str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))

from classify_learning import classify_learning  # noqa: E402
from compact_sources import DEFAULT_VAULT_DIR, Source, discover_sources, read_source, skip_source  # noqa: E402
from memory_node import SCHEMA_VERSION, contains_red_material, deterministic_node_id, sha256_text  # noqa: E402
from sensitive_content import public_findings  # noqa: E402
from tree_store import TreeStore, TreeStoreError, compute_project_id  # noqa: E402

try:
    from shared.active_context import active_context_from_payload  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover
    active_context_from_payload = None

SUMMARY_MARKERS = ("decision", "validated", "learning", "checkpoint", "handoff", "next action", "phase", "status")
TRANSCRIPT_MARKERS = ('"role":', "tool_calls", "response_item", "conversation transcript", "raw transcript")


@dataclass(frozen=True)
class Context:
    project_root: Path
    project_slug: str
    project_id: str
    workspace_instance_id: str
    repo_remote_hash: str
    branch: str
    commit: str
    session_id: str


@dataclass(frozen=True)
class Candidate:
    node: dict[str, Any]
    source_hash: str
    source_kind: str
    summary_hash: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact_space(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def normalize_summary(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def bounded(value: str, limit: int) -> str:
    text = compact_space(value)
    return text if len(text) <= limit else text[:limit].rstrip() + " ..."


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    metadata: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return metadata, "\n".join(lines[index + 1 :])
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        try:
            value = json.loads(raw.strip())
        except json.JSONDecodeError:
            value = raw.strip().strip("'\"")
        metadata[key.strip()] = str(value)
    return {}, text


def context_for(project_root: Path, project_id: str, session_id: str) -> Context:
    root = project_root.expanduser().resolve()
    # The TREE project_id keys the SHARED memory tree and MUST be the canonical
    # git-remote id (Wave 5, Addendum 4). The explicit ``project_id`` arg only
    # wins when supplied (its CLI default now carries RALPH_MEMORY_PROJECT_ID,
    # NOT the legacy RALPH_PROJECT_ID). Otherwise derive via compute_project_id
    # so codex and claude write/read the SAME tree dir.
    tree_project_id = project_id or compute_project_id(root)
    if active_context_from_payload is not None:
        active = active_context_from_payload({"cwd": str(root), "session_id": session_id})
        return Context(
            root,
            getattr(active, "project_slug", root.name),
            tree_project_id,
            getattr(active, "workspace_instance_id", "") or sha256_text(str(root))[:16],
            getattr(active, "remote_url_hash", "") or sha256_text(str(root))[:16],
            getattr(active, "branch", "") or "unknown",
            getattr(active, "sha", "") or "",
            session_id or getattr(active, "session_id", "") or "compact-to-nodes",
        )
    return Context(root, root.name, tree_project_id, sha256_text(str(root))[:16], sha256_text(str(root))[:16], "unknown", "", session_id or "compact-to-nodes")


def runtime_root(ralph_home: Path, project_id: str) -> Path:
    return ralph_home.expanduser() / "projects" / project_id


def source_payload(source: Source, text: str) -> tuple[dict[str, Any], str]:
    if source.kind == "checkpoint":
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}, compact_space(json.dumps(payload, sort_keys=True))
    return frontmatter(text)


def project_matches(metadata: dict[str, Any], context: Context) -> bool:
    value = metadata.get("project_id") or metadata.get("source_project_id")
    return bool(value and str(value) == context.project_id)


def summary_line(body: str) -> str:
    for raw in body.splitlines():
        line = compact_space(re.sub(r"^\s*(?:[-*]\s+|\d+\.\s+|#{1,6}\s+|>\s+)?", "", raw))
        if line and not line.startswith("|") and any(marker in line.lower() for marker in SUMMARY_MARKERS):
            return line
    for raw in body.splitlines():
        line = compact_space(raw)
        if line and not line.startswith("#"):
            return line
    return ""


def checkpoint_summary(payload: dict[str, Any]) -> tuple[str, str]:
    objective = compact_space(payload.get("objective"))
    phase = compact_space(payload.get("current_phase"))
    verified = compact_space(payload.get("last_verified_state"))
    next_action = compact_space(payload.get("next_action"))
    status = compact_space(payload.get("validation_status") or payload.get("status"))
    summary = bounded("Checkpoint: " + "; ".join(part for part in (phase, verified, status) if part), 280)
    detail = bounded(" ".join(part for part in (f"Objective: {objective}" if objective else "", f"Verified: {verified}" if verified else "", f"Next action: {next_action}" if next_action else "", f"Validation status: {status}" if status else "") if part), 700)
    return summary, detail


def memory_type_for(kind: str, summary: str, metadata: dict[str, Any]) -> str:
    lowered = summary.lower()
    if kind == "handoff":
        return "handoff"
    if kind == "checkpoint":
        return "validation" if metadata.get("validation_status") else "handoff"
    if lowered.startswith("decision"):
        return "decision"
    return "validation" if "validated" in lowered or "pass" in lowered else "fact"


def terms_for(summary: str, source_path: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", summary + " " + source_path):
        lowered = token.lower()
        if lowered not in seen:
            terms.append(token[:80])
            seen.add(lowered)
        if len(terms) >= 12:
            break
    return terms


def build_candidate(source: Source, text: str, context: Context, root: Path) -> tuple[Candidate | None, dict[str, Any] | None]:
    if any(marker in text.lower() for marker in TRANSCRIPT_MARKERS):
        return None, skip_source(source, "transcript_like")
    classification = classify_learning(text)
    if classification == "RED" or contains_red_material(text):
        item = skip_source(source, "red")
        item["findings"] = public_findings(text) or [{"kind": "classification", "label": "classified_red", "severity": "RED"}]
        return None, item
    try:
        metadata, body = source_payload(source, text)
    except (json.JSONDecodeError, TypeError):
        return None, skip_source(source, "invalid_source")
    if not project_matches(metadata, context):
        reason = "missing_provenance" if not (metadata.get("project_id") or metadata.get("source_project_id")) else "wrong_project"
        return None, skip_source(source, reason)
    summary, detailed = checkpoint_summary(metadata) if source.kind == "checkpoint" else (bounded(summary_line(body), 280), bounded(body, 700))
    if not summary:
        return None, skip_source(source, "no_summary")
    if classify_learning(summary) == "RED" or contains_red_material({"summary": summary, "detailed_summary": detailed}):
        return None, skip_source(source, "red_summary")
    source_hash = sha256_text(text)
    memory_type = memory_type_for(source.kind, summary, metadata)
    stamp = now_iso()
    payload = {
        "schema_version": SCHEMA_VERSION, "project_id": context.project_id, "workspace_instance_id": context.workspace_instance_id, "repo_remote_hash": context.repo_remote_hash, "branch": context.branch, "commit": context.commit, "session_id": context.session_id,
        "memory_type": memory_type, "sensitivity": classification, "authority": "non_authoritative", "summary": summary, "detailed_summary": detailed, "trigger": {"terms": terms_for(summary, source.relative_path), "paths": [source.relative_path]},
        "topic_tags": ["memory-tree-v2", source.kind], "entities": [term for term in terms_for(summary, source.relative_path) if term[:1].isupper()][:8], "source_paths": [source.relative_path], "source_description": f"Compacted from Ralph {source.kind} safe summary.", "raw_ref": None, "links": [],
        "salience": {"recency": 0.5, "frequency": 0.0, "validation": 0.6 if memory_type == "validation" else 0.4, "task_fit": 0.5}, "quality": {"confidence": 0.75 if source.kind in {"handoff", "checkpoint"} else 0.68, "provenance_complete": True, "validation_status": metadata.get("validation_status", "not_run"), "stale": False, "deprecated": False, "source_hash": source_hash},
        "created_at": stamp, "updated_at": stamp, "compaction_reason": "phase_04_compact_to_nodes",
    }
    payload["node_id"] = deterministic_node_id(payload)
    return Candidate(payload, source_hash, source.kind, sha256_text(normalize_summary(summary))), None


def report_candidate(candidate: Candidate) -> dict[str, Any]:
    node = candidate.node
    return {"node_id": node["node_id"], "memory_type": node["memory_type"], "sensitivity": node["sensitivity"], "confidence": node["quality"]["confidence"], "source_kind": candidate.source_kind, "source_paths": node["source_paths"], "source_hash": candidate.source_hash, "summary_hash": candidate.summary_hash, "trigger_terms": list(node["trigger"]["terms"])[:12]}


def candidate_keys(candidate: Candidate) -> tuple[str, str, str]:
    node = candidate.node
    return candidate.source_hash, normalize_summary(str(node.get("summary", ""))), f"{node.get('memory_type')}|" + "|".join(str(path) for path in node.get("source_paths", []))


def existing_keys(store: TreeStore, project_id: str) -> tuple[set[str], set[str], set[str]]:
    by_source: set[str] = set()
    by_summary: set[str] = set()
    by_path_type: set[str] = set()
    for node in store.list_nodes(project_id):
        quality = node.get("quality") if isinstance(node.get("quality"), dict) else {}
        if quality.get("source_hash"):
            by_source.add(str(quality["source_hash"]))
        by_summary.add(normalize_summary(str(node.get("summary", ""))))
        by_path_type.add(f"{node.get('memory_type')}|" + "|".join(str(path) for path in node.get("source_paths", [])))
    return by_source, by_summary, by_path_type


def dedupe(candidates: list[Candidate], store: TreeStore, project_id: str) -> tuple[list[Candidate], list[dict[str, Any]], int]:
    seen_source, seen_summary, seen_path = existing_keys(store, project_id)
    unique: list[Candidate] = []
    skipped: list[dict[str, Any]] = []
    duplicates = 0
    for candidate in candidates:
        source_key, summary_key, path_key = candidate_keys(candidate)
        reason = "duplicate_source_hash" if source_key in seen_source else "duplicate_summary" if summary_key in seen_summary else "duplicate_source_path_memory_type" if path_key in seen_path else ""
        if reason:
            duplicates += 1
            skipped.append({"source_path": candidate.node["source_paths"][0], "source_kind": candidate.source_kind, "reason": reason, "node_id": candidate.node["node_id"]})
            continue
        seen_source.add(source_key); seen_summary.add(summary_key); seen_path.add(path_key); unique.append(candidate)
    return unique, skipped, duplicates


def reason_counts(skipped: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in skipped:
        reason = str(item.get("reason", "unknown"))
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def build_report(context: Context, ralph_home: Path, write: bool, max_items: int, include_curated_vault: bool = False, vault_dir: Path = DEFAULT_VAULT_DIR) -> dict[str, Any]:
    root = runtime_root(ralph_home, context.project_id)
    store = TreeStore(ralph_home)
    sources, skipped = discover_sources(root, max_items, vault_dir if include_curated_vault else None, context.project_slug)
    candidates: list[Candidate] = []
    for source in sources:
        text, source_skip = read_source(source)
        candidate, candidate_skip = (None, source_skip) if source_skip else build_candidate(source, text or "", context, root)
        candidates.extend([candidate] if candidate else [])
        skipped.extend([candidate_skip] if candidate_skip else [])
    unique, duplicate_skips, duplicates = dedupe(candidates, store, context.project_id)
    skipped.extend(duplicate_skips)
    written: list[dict[str, Any]] = []
    if write:
        for candidate in unique:
            try:
                store.create_node(candidate.node)
                written.append(report_candidate(candidate))
            except (TreeStoreError, ValueError):
                skipped.append({"source_path": candidate.node["source_paths"][0], "source_kind": candidate.source_kind, "reason": "write_failed", "node_id": candidate.node["node_id"]})
    return {"created_at": now_iso(), "project_id": context.project_id, "project_slug": context.project_slug, "dry_run": not write, "candidates": [report_candidate(item) for item in unique], "written": written, "skipped": skipped, "skip_reasons": reason_counts(skipped), "red_skipped": sum(1 for item in skipped if item.get("reason") in {"red", "red_summary"}), "duplicate_candidates": duplicates}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact safe Ralph runtime memory into MemoryNode v2 candidates.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--dry-run", action="store_true", help="Default: report only.")
    parser.add_argument("--write", action="store_true", help="Write deduplicated candidates.")
    parser.add_argument("--project-id", default=os.environ.get("RALPH_MEMORY_PROJECT_ID", ""))
    parser.add_argument("--ralph-home", default=os.environ.get("RALPH_HOME", "~/.ralph-codex"))
    parser.add_argument("--session-id", default=os.environ.get("CODEX_SESSION_ID") or os.environ.get("RALPH_SESSION_ID", "compact-to-nodes"))
    parser.add_argument("--max-items", type=int, default=1000)
    parser.add_argument("--include-curated-vault", action="store_true", help="Also scan recall-eligible curated MiVault markdown; never inbox/raw.")
    parser.add_argument("--vault-dir", default=os.environ.get("VAULT_DIR", str(DEFAULT_VAULT_DIR)))
    args = parser.parse_args()
    if args.write and args.dry_run:
        parser.error("--write and --dry-run are mutually exclusive")
    context = context_for(Path(args.project_root), args.project_id, args.session_id)
    print(json.dumps(build_report(context, Path(args.ralph_home), bool(args.write), max(0, args.max_items), bool(args.include_curated_vault), Path(args.vault_dir)), ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
