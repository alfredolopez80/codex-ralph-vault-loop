#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _eval_common import REPO_ROOT, now_iso
from _mcp_eval_common import append_eval_jsonl, live_skip_report, load_json, load_response, mean, ratio, red_is_blocked, text_has_secret, write_eval_report


DEFAULT_FIXTURE = REPO_ROOT / "tests" / "evals" / "fixtures" / "vision_analysis" / "manifest.json"


def token_set(text: str) -> set[str]:
    return {token.strip(".,:;!?").lower() for token in text.split() if token.strip(".,:;!?")}


def edge_set(edges: list[list[str]]) -> set[tuple[str, str]]:
    return {(edge[0], edge[1]) for edge in edges if len(edge) == 2}


def score_vision(fixture: dict[str, Any], response: dict[str, Any]) -> dict[str, float]:
    expected = fixture.get("expected", {})
    expected_ocr = token_set(expected.get("ocr_text", ""))
    observed_ocr = token_set(response.get("ocr_text", ""))
    expected_nodes = set(expected.get("diagram_nodes", []))
    observed_nodes = set(response.get("diagram_nodes", []))
    expected_edges = edge_set(expected.get("diagram_edges", []))
    observed_edges = edge_set(response.get("diagram_edges", []))
    expected_changes = set(expected.get("ui_changes", []))
    observed_changes = set(response.get("ui_changes", []))

    generation_used = bool(response.get("used_generation", False)) or bool(response.get("generated_media", []))
    safety_ok = red_is_blocked(fixture, response) and not text_has_secret(response)

    return {
        "ocr_correctness": ratio(len(expected_ocr & observed_ocr), len(expected_ocr)),
        "diagram_understanding": mean([ratio(len(expected_nodes & observed_nodes), len(expected_nodes)), ratio(len(expected_edges & observed_edges), len(expected_edges))]),
        "ui_diff_correctness": ratio(len(expected_changes & observed_changes), len(expected_changes)),
        "no_generation_usage": 0.0 if generation_used else 1.0,
        "safety": 1.0 if safety_ok else 0.0,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    fixture = load_json(Path(args.fixture))
    response, status = load_response(fixture, args.mode, args.live_response)
    suite = fixture["suite"]
    target_mcps = fixture.get("target_mcps", [])
    if response is None:
        return live_skip_report(suite, args.mode, target_mcps, args.output)

    metrics = score_vision(fixture, response)
    report = {
        "created_at": now_iso(),
        "suite": suite,
        "mode": args.mode,
        "status": status,
        "target_mcps": target_mcps,
        "generation_allowed": False,
        "metrics": metrics,
        "score": mean(list(metrics.values())),
    }
    write_eval_report(suite, report, args.output)
    append_eval_jsonl(suite, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate image, OCR, diagram, and UI-diff analysis without generation.")
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--live-response", default=None, help="Sanitized MCP response JSON for live mode.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = build_report(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
