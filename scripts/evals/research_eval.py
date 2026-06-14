#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _eval_common import REPO_ROOT, now_iso
from _eval_common import safe_json_text
from _mcp_eval_common import append_eval_jsonl, live_skip_report, load_json, load_response
from _mcp_eval_common import mean, ratio, red_is_blocked, text_has_secret, write_eval_report


DEFAULT_FIXTURE = REPO_ROOT / "tests" / "evals" / "fixtures" / "research_citation" / "manifest.json"


def score_research(fixture: dict[str, Any], response: dict[str, Any]) -> dict[str, float]:
    sources = response.get("sources", [])
    source_ids = {source.get("id") for source in sources}
    official_sources = [source for source in sources if source.get("type") in {"primary", "official"}]
    expected_claims = fixture.get("expected_claims", [])
    claims = {claim.get("id"): claim for claim in response.get("claims", [])}
    supported_claims = 0
    for expected in expected_claims:
        claim = claims.get(expected.get("id"), {})
        support = set(claim.get("supported_by", []))
        if support and support <= source_ids:
            supported_claims += 1

    min_year = int(fixture.get("min_source_year", 0))
    if fixture.get("requires_recency", False):
        recent_sources = [source for source in sources if int(source.get("published_year", 0)) >= min_year]
        recency_fit = ratio(len(recent_sources), len(sources))
    else:
        recency_fit = 1.0

    domains = {source.get("domain") for source in sources if source.get("domain")}
    max_cost = float(fixture.get("max_cost_units", 1))
    cost_units = float(response.get("cost_units", max_cost))

    return {
        "source_quality": ratio(len(official_sources), len(sources)),
        "faithfulness": ratio(supported_claims, len(expected_claims)),
        "recency_fit": recency_fit,
        "source_diversity": ratio(len(domains), int(fixture.get("min_unique_domains", 1))),
        "actionability": ratio(len(response.get("actions", [])), int(fixture.get("min_actions", 1))),
        "cost": clamp_cost(cost_units, max_cost),
    }


def clamp_cost(cost_units: float, max_cost: float) -> float:
    if cost_units <= max_cost:
        return 1.0
    return max(0.0, round(max_cost / cost_units, 4))


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    fixture = load_json(Path(args.fixture))
    response, status = load_response(fixture, args.mode, args.live_response)
    suite = fixture["suite"]
    target_mcps = fixture.get("target_mcps", [])
    if response is None:
        return live_skip_report(suite, args.mode, target_mcps, args.output)

    red_blocked = red_is_blocked(fixture, response)
    no_secret = not text_has_secret(response)
    metrics = score_research(fixture, response)
    safety_ok = red_blocked and no_secret
    score = mean(list(metrics.values()) + [1.0 if safety_ok else 0.0])
    report = {
        "created_at": now_iso(),
        "suite": suite,
        "mode": args.mode,
        "status": status,
        "target_mcps": target_mcps,
        "metrics": metrics,
        "red_blocked": red_blocked,
        "no_secret_leak": no_secret,
        "score": score,
    }
    write_eval_report(suite, report, args.output)
    append_eval_jsonl(suite, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate research MCP citation quality in mock or live mode.")
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--live-response", default=None, help="Sanitized MCP response JSON for live mode.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = build_report(args)
    print(safe_json_text(report))  # lgtm[py/clear-text-logging-sensitive-data]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
