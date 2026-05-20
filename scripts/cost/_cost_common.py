from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SECURITY_DIR = Path(__file__).resolve().parents[1] / "security"
if str(SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(SECURITY_DIR))

from sensitive_content import classify_text, redact_text as redact_sensitive_text  # noqa: E402


DEFAULT_RALPH_HOME = Path("~/.ralph-codex").expanduser()
SENSITIVITIES = {"GREEN", "YELLOW", "RED"}
FAST_TASKS = {"log_summary", "diff_summary", "test_ideas", "logs", "diffs"}
OPENCLAW_TASKS = {"openclaw", "openclaw_like", "command_following", "small_agentic"}
DEEP_TASKS = {"architecture_counterpart", "architecture", "debugging", "design_review", "failure_analysis"}
INTENT_ALIASES = {
    "log_summary": "logs",
    "logs": "logs",
    "diff_summary": "diff",
    "diffs": "diff",
    "pr_summary": "summary",
    "summary": "summary",
    "test_ideas": "test-ideas",
    "test_idea": "test-ideas",
    "openclaw": "implementation-support",
    "openclaw_like": "implementation-support",
    "command_following": "implementation-support",
    "small_agentic": "implementation-support",
    "implementation_support": "implementation-support",
    "code_review": "implementation-support",
    "debugging": "debugging",
    "failure_analysis": "debugging",
    "architecture_counterpart": "architecture",
    "architecture": "architecture",
    "design_review": "architecture",
    "spec_review": "spec-review",
    "spec-review": "spec-review",
    "claim_adjudication": "claim-adjudication",
    "claim-adjudication": "claim-adjudication",
    "reviewer_disagreement": "claim-adjudication",
    "research": "research",
    "web_search": "research",
    "url_reading": "url-reading",
    "url-reading": "url-reading",
    "repo_reading": "repo-reading",
    "repo-reading": "repo-reading",
    "vision": "vision",
    "image_understanding": "vision",
    "quick_image": "minimax-vision",
}
PROTOCOL_ROUTES = {
    "codex_direct": "local",
    "codex_main_local": "local",
    "mcp_fast_minimax": "mcp:minimax-fast",
    "mcp_fast_zai": "mcp:zai-fast",
    "mcp_fast_coding": "mcp:zai-fast",
    "mcp_deep_counterpart": "mcp:zai-deep",
    "codex_main_with_gates": "local",
}
LANE_PROTOCOL_ROUTES = {
    "local": "local",
    "minimax-fast": "mcp:minimax-fast",
    "zai-fast": "mcp:zai-fast",
    "zai-deep": "mcp:zai-deep",
    "zai-search": "mcp:zai-search",
    "zai-reader": "mcp:zai-reader",
    "zai-repo": "mcp:zai-repo",
    "zai-vision": "mcp:zai-vision",
    "minimax-vision": "mcp:minimax-vision",
    "codex-subagent": "codex-subagent",
    "fallback-local": "fallback-local",
}
LANE_TO_TOOL = {
    "minimax-fast": "ralph_coding_models.minimax_agentic_fast",
    "zai-fast": "ralph_coding_models.zai_coding_fast",
    "zai-deep": "ralph_coding_models.zai_coding_deep",
    "zai-search": "zai_web_search.web_search_prime",
    "zai-reader": "zai_web_reader.webReader",
    "zai-repo": "zai_zread.search_doc",
    "zai-vision": "zai_vision",
    "minimax-vision": "minimax_coding_tools.understand_image",
}
LANE_TO_MODEL = {
    "minimax-fast": "MiniMax-M2.7-highspeed",
    "zai-fast": "GLM-5-Turbo",
    "zai-deep": "GLM-5.1",
}
LANE_TO_ROLE = {
    "minimax-fast": "log summarizer",
    "zai-fast": "implementation advisor",
    "zai-deep": "debug analyst",
    "zai-search": "researcher",
    "zai-reader": "researcher",
    "zai-repo": "researcher",
    "zai-vision": "vision analyst",
    "minimax-vision": "vision analyst",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ralph_home() -> Path:
    return Path(os.environ.get("RALPH_HOME", str(DEFAULT_RALPH_HOME))).expanduser()


def normalize_sensitivity(value: str) -> str:
    sensitivity = value.strip().upper()
    if sensitivity not in SENSITIVITIES:
        raise ValueError(f"sensitivity must be one of {sorted(SENSITIVITIES)}")
    return sensitivity


def normalize_complexity(value: int | str) -> int:
    complexity = int(value)
    if complexity < 1 or complexity > 10:
        raise ValueError("complexity must be between 1 and 10")
    return complexity


def redact_text(text: str) -> tuple[str, bool]:
    return redact_sensitive_text(text)


def redaction_report(text: str) -> dict[str, Any]:
    report = classify_text(text)
    payload = report.public_dict()
    payload["redacted"] = report.redacted_text
    payload["allowed_external"] = report.classification != "RED"
    return payload


def estimate_context(text: str) -> dict[str, int]:
    chars = len(text)
    words = len(text.split())
    estimated_tokens = max(1, (chars + 3) // 4) if chars else 0
    return {"chars": chars, "words": words, "estimated_tokens": estimated_tokens}


def intent_for_task(task: str, explicit_intent: str | None = None) -> str:
    raw = (explicit_intent or task).strip().lower().replace("-", "_")
    return INTENT_ALIASES.get(raw, raw.replace("_", "-") or "unknown")


def verification_for(lane: str) -> str:
    if lane == "local":
        return "Codex verifies with local file inspection and targeted tests."
    if lane in {"zai-search", "zai-reader", "zai-repo"}:
        return "Codex verifies source relevance and applies findings locally before acting."
    if lane in {"zai-vision", "minimax-vision"}:
        return "Codex cross-checks visual findings against local UI, files, or user-provided evidence."
    return "Codex inspects the advisory output, adapts it locally, and validates with targeted checks."


def reason_for(intent: str, lane: str) -> str:
    if lane == "local":
        return "No external MCP lane adds enough value for this intent or sensitivity."
    if lane == "minimax-fast":
        return "Fast compression and lightweight synthesis fit this intent."
    if lane == "zai-fast":
        return "Small agentic reasoning support fits this implementation-support intent."
    if lane == "zai-deep":
        return "Deep analysis is useful for this higher-judgment intent."
    if lane == "zai-search":
        return "Current external research is the requested value."
    if lane == "zai-reader":
        return "A specific safe URL should be read through the Z.ai reader lane."
    if lane == "zai-repo":
        return "Public repository research fits the Z.ai repo-reading lane."
    if lane == "zai-vision":
        return "Visual understanding fits the Z.ai vision analysis lane."
    if lane == "minimax-vision":
        return "Quick visual understanding fits the MiniMax vision lane."
    return "Selected by intent, safety, and expected verification value."


def role_for(intent: str, lane: str) -> str:
    if intent == "spec-review":
        return "spec reviewer"
    if intent == "claim-adjudication":
        return "claim adjudicator"
    if intent == "test-ideas":
        return "implementation advisor"
    return LANE_TO_ROLE.get(lane, "implementation advisor")


def external_mcp_brief(tool: str | None, lane: str, intent: str, sens: str) -> dict[str, Any] | None:
    if tool is None or lane == "local":
        return None
    provider = "MiniMax" if lane.startswith("minimax") else "Z.ai"
    return {
        "tool": provider,
        "role": role_for(intent, lane),
        "sensitivity": "YELLOW-sanitized" if sens == "YELLOW" else sens,
        "context_minimized": True,
        "task": f"Handle the {intent} request with concise, evidence-oriented output.",
        "constraints": "Do not decide final outcome, edit files, request secrets, or process RED content.",
        "required_output": ["findings or verdict", "evidence", "confidence", "risks", "recommended next action"],
        "codex_final_owner": True,
    }


def route_decision_payload(sens: str, intent: str, level: int, lane: str, tool: str | None, reason: str, verification: str, fallback: str) -> dict[str, Any]:
    return {
        "sensitivity": sens,
        "intent": intent,
        "complexity": level,
        "route": lane,
        "tool": tool,
        "reason": reason,
        "verification": verification,
        "fallback": fallback,
    }


def blocked_route(task: str, level: int, sens: str, reason: str, findings: list[dict[str, str]] | None = None, intent: str | None = None) -> dict[str, Any]:
    normalized_intent = intent or intent_for_task(task)
    verification = "Keep work local; do not externalize RED or sensitive context."
    return {
        "allowed": False,
        "blocked": True,
        "reason": reason,
        "route": "codex_main_local",
        "protocol_route": "local",
        "lane": "local",
        "intent": normalized_intent,
        "tool": None,
        "model": None,
        "requires_codex_synthesis": True,
        "sensitivity": "RED" if sens == "RED" or findings else sens,
        "complexity": level,
        "task_type": task,
        "verification": verification,
        "fallback": "RED or sensitive content blocks external MCP use.",
        "route_decision": route_decision_payload(
            "RED" if sens == "RED" or findings else sens,
            normalized_intent,
            level,
            "local",
            None,
            reason,
            verification,
            "RED or sensitive content blocks external MCP use.",
        ),
        "external_mcp_brief": None,
        "sensitive_findings": findings or [],
    }


def route_task(task_type: str, complexity: int | str, sensitivity: str, text: str | None = None, intent: str | None = None) -> dict[str, Any]:
    task = task_type.strip().lower().replace("-", "_")
    level = normalize_complexity(complexity)
    sens = normalize_sensitivity(sensitivity)
    normalized_intent = intent_for_task(task, intent)
    sensitivity_scan = classify_text(text or "", sens)

    if sens == "RED" or sensitivity_scan.classification == "RED":
        return blocked_route(
            task,
            level,
            sens,
            "RED content must stay local and cannot be externalized.",
            [finding.public_dict() for finding in sensitivity_scan.findings],
            normalized_intent,
        )

    if normalized_intent in {"logs", "diff", "summary", "test-ideas"}:
        route, lane = "mcp_fast_minimax", "minimax-fast"
    elif normalized_intent == "implementation-support":
        route = "mcp_fast_zai" if task in OPENCLAW_TASKS else "mcp_fast_coding"
        lane = "zai-fast"
    elif normalized_intent in {"debugging", "architecture", "spec-review", "claim-adjudication"}:
        route, lane = "mcp_deep_counterpart", "zai-deep"
    elif normalized_intent == "research":
        route, lane = "zai_web_search", "zai-search"
    elif normalized_intent == "url-reading":
        route, lane = "zai_web_reader", "zai-reader"
    elif normalized_intent == "repo-reading":
        route, lane = "zai_zread", "zai-repo"
    elif normalized_intent == "vision":
        route, lane = "zai_vision", "zai-vision"
    elif normalized_intent == "minimax-vision":
        route, lane = "minimax_vision", "minimax-vision"
    else:
        route, lane = "codex_direct", "local"

    if level >= 7 and lane in {"zai-deep", "zai-fast", "minimax-fast"}:
        route = "codex_main_with_gates"
    tool = LANE_TO_TOOL.get(lane)
    model = LANE_TO_MODEL.get(lane)
    if route == "codex_direct":
        tool, model = None, None

    verification = verification_for(lane)
    reason = reason_for(normalized_intent, lane)
    fallback = "none" if lane != "local" else "local route selected by intent policy"
    protocol_route = PROTOCOL_ROUTES.get(route) or LANE_PROTOCOL_ROUTES.get(lane, "fallback-local")

    return {
        "allowed": True,
        "blocked": False,
        "route": route,
        "protocol_route": protocol_route,
        "lane": lane,
        "intent": normalized_intent,
        "tool": tool,
        "model": model,
        "requires_codex_synthesis": route != "codex_direct",
        "sensitivity": sens,
        "complexity": level,
        "task_type": task,
        "reason": reason,
        "verification": verification,
        "fallback": fallback,
        "route_decision": route_decision_payload(sens, normalized_intent, level, lane, tool, reason, verification, fallback),
        "external_mcp_brief": external_mcp_brief(tool, lane, normalized_intent, sens),
        "sensitive_findings": [],
        "mcps": [
            "ralph_coding_models",
            "zai_web_search",
            "zai_web_reader",
            "zai_zread",
            "zai_vision",
            "minimax_coding_tools",
        ],
    }


def ledger_path() -> Path:
    root = ralph_home() / "cost"
    root.mkdir(parents=True, exist_ok=True)
    return root / "routing-ledger.jsonl"


def append_ledger(entry: dict[str, Any]) -> Path:
    path = ledger_path()
    payload = {"created_at": now_iso(), **entry}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
    return path
