from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from _eval_common import REPORT_DIR, detect_secret_leak, now_iso, write_json


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 1.0
    return clamp(float(numerator) / float(denominator))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_response(fixture: dict[str, Any], mode: str, live_response: str | None) -> tuple[dict[str, Any] | None, str]:
    if mode == "mock":
        return fixture.get("mock_response", {}), "completed"
    if live_response:
        return load_json(Path(live_response)), "completed"
    return None, "skipped_no_mcp_bridge"


def text_has_secret(payload: Any) -> bool:
    if isinstance(payload, str):
        return detect_secret_leak(payload)
    if isinstance(payload, dict):
        return any(text_has_secret(value) for value in payload.values())
    if isinstance(payload, list):
        return any(text_has_secret(value) for value in payload)
    return False


def red_is_blocked(fixture: dict[str, Any], response: dict[str, Any] | None) -> bool:
    if fixture.get("sensitivity", "GREEN").upper() == "RED":
        return response is None or bool(response.get("blocked", False))
    probe = fixture.get("red_probe")
    if not probe:
        return True
    return bool(probe.get("expected_blocked", True)) and not bool(probe.get("externalized", False))


def write_eval_report(suite: str, payload: dict[str, Any], output: str | None) -> Path:
    path = Path(output) if output else REPORT_DIR / f"{suite}_latest.json"
    payload["report_path"] = str(path)
    write_json(path, payload)
    return path


def append_eval_jsonl(suite: str, payload: dict[str, Any]) -> Path:
    path = REPORT_DIR / f"{suite}_runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "created_at": payload.get("created_at", now_iso()),
        "suite": suite,
        "mode": payload.get("mode"),
        "status": payload.get("status"),
        "score": payload.get("score"),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")
    return path


def live_skip_report(suite: str, mode: str, target_mcps: list[str], output: str | None) -> dict[str, Any]:
    payload = {
        "created_at": now_iso(),
        "suite": suite,
        "mode": mode,
        "status": "skipped_no_mcp_bridge",
        "target_mcps": target_mcps,
        "reason": "Live mode requires --live-response with sanitized MCP output; Python eval scripts do not call Codex MCP tools directly.",
        "metrics": {},
        "score": 0.0,
    }
    write_eval_report(suite, payload, output)
    append_eval_jsonl(suite, payload)
    return payload


def default_vault_dir() -> Path:
    return Path(os.environ.get("VAULT_DIR", "~/Documents/Obsidian/MiVault")).expanduser()
