#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from _eval_common import REPORT_DIR, REPO_ROOT, load_json, load_scorecard, now_iso, score_run, write_json


DEFAULT_FIXTURE = REPO_ROOT / "tests" / "evals" / "fixtures" / "autoresearch_toy_speed"
DEFAULT_SCORECARD = REPO_ROOT / "config" / "scorecards" / "ralph_autoresearch_v1.yaml"
DEFAULT_OUTPUT = REPORT_DIR / "autoresearch_toy_speed_latest.json"
DEFAULT_JSONL = REPORT_DIR / "autoresearch_runs.jsonl"
PROTECTED_HARNESS_PATHS = (
    REPO_ROOT / "scripts" / "evals",
    REPO_ROOT / "config" / "scorecards",
)


def iter_digest_files(paths: list[Path] | tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.is_file()))
        elif path.exists():
            files.append(path)
    return [
        item
        for item in files
        if "__pycache__" not in item.parts and item.suffix != ".pyc" and ".ralph-codex" not in item.parts
    ]


def digest_paths(paths: list[Path] | tuple[Path, ...]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in iter_digest_files(paths):
        try:
            key = str(path.relative_to(REPO_ROOT))
        except ValueError:
            key = str(path)
        digests[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def changed_digest_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    keys = set(before) | set(after)
    return sorted(key for key in keys if before.get(key) != after.get(key))


def load_fixture_path(fixture: Path, raw_path: str) -> dict[str, Any]:
    path = Path(raw_path)
    if not path.is_absolute():
        path = fixture / path
    return load_json(path)


def score_payload(scorecard: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return score_run(scorecard, payload.get("metrics", payload), payload.get("hard_gates", payload))


def score_pair(scorecard: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "baseline": score_payload(scorecard, baseline),
        "candidate": score_payload(scorecard, candidate),
    }


def load_suite_scores(fixture: Path, scorecard: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    manifest = load_json(fixture / "manifest.json")
    overall = score_pair(
        scorecard,
        load_fixture_path(fixture, manifest.get("baseline", "baseline_metrics.json")),
        load_fixture_path(fixture, manifest.get("candidate", "candidate_metrics.json")),
    )

    splits: dict[str, Any] = {}
    for split_name, split_path in manifest.get("splits", {}).items():
        payload = load_fixture_path(fixture, split_path)
        splits[split_name] = score_pair(scorecard, payload["baseline"], payload["candidate"])

    decision_source = "holdout" if "holdout" in splits else "overall"
    return manifest | {"overall": overall, "splits_scored": splits}, splits.get("holdout", overall), decision_source


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def vault_target_path(suite: str) -> Path:
    vault_dir = Path(os.environ.get("VAULT_DIR", "~/Documents/Obsidian/MiVault")).expanduser()
    stamp = now_iso().replace(":", "").replace("+0000", "Z")
    return vault_dir / "global" / "decisions" / f"autoresearch-{suite}-{stamp}.md"


def persist_vault_result(report: dict[str, Any]) -> Path:
    target = vault_target_path(report["suite"])
    target.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "---",
        "classification: GREEN",
        f"source: {report['suite']}",
        f"created_at: {report['created_at']}",
        "kind: autoresearch-result",
        "---",
        "",
        f"# AutoResearch {report['suite']}",
        "",
        f"Decision: {report['decision']}",
        f"Score delta: {report['delta']}",
        f"Scorecard: {report['scorecard']}",
        "",
    ]
    target.write_text("\n".join(body), encoding="utf-8")
    return target


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    fixture = Path(args.fixture).resolve()
    scorecard_path = Path(args.scorecard).resolve()
    before_harness = digest_paths(PROTECTED_HARNESS_PATHS)
    before_fixture = digest_paths((fixture,))

    scorecard = load_scorecard(scorecard_path)
    suite_report, decision_scores, decision_source = load_suite_scores(fixture, scorecard)
    threshold = args.min_delta if args.min_delta is not None else float(suite_report.get("decision_threshold", 0.01))

    after_harness = digest_paths(PROTECTED_HARNESS_PATHS)
    after_fixture = digest_paths((fixture,))
    harness_changes = changed_digest_paths(before_harness, after_harness)
    fixture_changes = changed_digest_paths(before_fixture, after_fixture)

    baseline_score = float(decision_scores["baseline"]["score"])
    candidate_score = float(decision_scores["candidate"]["score"])
    delta = round(candidate_score - baseline_score, 4)
    gates_passed = bool(decision_scores["candidate"]["hard_gates"]["passed"])
    protected = not harness_changes and not fixture_changes
    keep = delta >= threshold and gates_passed and protected

    report = {
        "created_at": now_iso(),
        "suite": suite_report["suite"],
        "scorecard": scorecard["id"],
        "scorecard_version": scorecard["version"],
        "dry_run": not args.persist_vault,
        "decision": "keep" if keep else "discard",
        "decision_source": decision_source,
        "decision_threshold": threshold,
        "delta": delta,
        "hard_gates_passed": gates_passed,
        "eval_harness_unchanged": not harness_changes,
        "fixture_unchanged": not fixture_changes,
        "changed_harness_paths": harness_changes,
        "changed_fixture_paths": fixture_changes,
        "overall": suite_report["overall"],
        "splits": suite_report["splits_scored"],
        "notes": [
            "Scorecards and fixtures are read-only inputs during the run.",
            "Keep/discard is based on holdout delta when a holdout split exists.",
        ],
    }

    if args.persist_vault and keep:
        report["vault_saved_to"] = str(persist_vault_result(report))
    else:
        report["vault_saved_to"] = None

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic Codex AutoResearch dry-run fixture.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--scorecard", default=str(DEFAULT_SCORECARD))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--jsonl", default=str(DEFAULT_JSONL))
    parser.add_argument("--min-delta", type=float, default=None)
    parser.add_argument("--persist-vault", action="store_true", help="Persist PASS results to the local Obsidian vault.")
    args = parser.parse_args()

    report = build_report(args)
    write_json(Path(args.output), report)
    append_jsonl(Path(args.jsonl), {"created_at": report["created_at"], "suite": report["suite"], "decision": report["decision"], "delta": report["delta"]})
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
