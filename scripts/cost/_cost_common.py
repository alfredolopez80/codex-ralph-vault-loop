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
PROTOCOL_ROUTES = {
    "codex_direct": "local",
    "codex_main_local": "local",
    "mcp_fast_minimax": "mcp:minimax-fast",
    "mcp_fast_zai": "mcp:zai-fast",
    "mcp_fast_coding": "mcp:zai-fast",
    "mcp_deep_counterpart": "mcp:zai-deep",
    "codex_main_with_gates": "local",
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


def blocked_route(task: str, level: int, sens: str, reason: str, findings: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "allowed": False,
        "blocked": True,
        "reason": reason,
        "route": "codex_main_local",
        "protocol_route": "local",
        "tool": None,
        "model": None,
        "requires_codex_synthesis": True,
        "sensitivity": "RED" if sens == "RED" or findings else sens,
        "complexity": level,
        "task_type": task,
        "sensitive_findings": findings or [],
    }


def route_task(task_type: str, complexity: int | str, sensitivity: str, text: str | None = None) -> dict[str, Any]:
    task = task_type.strip().lower().replace("-", "_")
    level = normalize_complexity(complexity)
    sens = normalize_sensitivity(sensitivity)
    sensitivity_scan = classify_text(text or "", sens)

    if sens == "RED" or sensitivity_scan.classification == "RED":
        return blocked_route(
            task,
            level,
            sens,
            "RED content must stay local and cannot be externalized.",
            [finding.public_dict() for finding in sensitivity_scan.findings],
        )

    if level <= 2:
        if task in OPENCLAW_TASKS:
            route, tool, model = "mcp_fast_zai", "ralph_coding_models.zai_coding_fast", "GLM-5-Turbo"
        elif task in FAST_TASKS:
            route, tool, model = "mcp_fast_minimax", "ralph_coding_models.minimax_agentic_fast", "MiniMax-M2.7-highspeed"
        else:
            route, tool, model = "codex_direct", None, None
    elif level <= 4:
        if task in FAST_TASKS:
            route, tool, model = "mcp_fast_minimax", "ralph_coding_models.minimax_agentic_fast", "MiniMax-M2.7-highspeed"
        else:
            route, tool, model = "mcp_fast_coding", "ralph_coding_models.zai_coding_fast", "GLM-5-Turbo"
    elif level <= 6:
        route, tool, model = "mcp_deep_counterpart", "ralph_coding_models.zai_coding_deep", "GLM-5.1"
    else:
        route, tool, model = "codex_main_with_gates", None, None
        if sens != "RED" and task in DEEP_TASKS:
            tool, model = "ralph_coding_models.zai_coding_deep", "GLM-5.1"

    return {
        "allowed": True,
        "blocked": False,
        "route": route,
        "protocol_route": PROTOCOL_ROUTES.get(route, "fallback-local"),
        "tool": tool,
        "model": model,
        "requires_codex_synthesis": route != "codex_direct",
        "sensitivity": sens,
        "complexity": level,
        "task_type": task,
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
