#!/usr/bin/env python3
"""Codex Stop hook that asks Codex to rewrite slop-heavy final responses."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_THRESHOLD = 60
MIN_WORDS = 10
MAX_TEXT_BYTES = 60_000


def respond(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True))


def word_count(text: str) -> int:
    return len(text.split())


def threshold() -> int:
    raw = os.environ.get("CODEX_SLOP_GUARD_THRESHOLD", str(DEFAULT_THRESHOLD))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_THRESHOLD
    return max(0, min(100, value))


def log_result(score: int | None, band: str | None, blocked: bool, reason: str | None = None) -> None:
    log_dir = Path.home() / ".ralph-codex" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        line = {
            "event": "codex_stop_slop_guard",
            "score": score,
            "band": band,
            "blocked": blocked,
            "reason": reason,
        }
        with (log_dir / "slop_guard_hooks.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=True) + "\n")
    except OSError:
        pass


def run_slop_guard(text: str) -> dict[str, Any]:
    command = ["uvx", "--from", "slop-guard", "sg", "-j", "-"]
    completed = subprocess.run(
        command,
        input=text,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError((completed.stderr or completed.stdout or "slop-guard failed").strip())
    return json.loads(completed.stdout)


def main() -> int:
    if os.environ.get("CODEX_SLOP_GUARD_ENABLED", "1") == "0":
        return 0

    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        log_result(None, None, False, "invalid hook input")
        return 0

    if hook_input.get("stop_hook_active"):
        return 0

    text = hook_input.get("last_assistant_message") or ""
    if not isinstance(text, str) or word_count(text) < MIN_WORDS:
        return 0

    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        log_result(None, None, False, "message too large")
        return 0

    try:
        result = run_slop_guard(text)
    except Exception as exc:  # noqa: BLE001 - hooks should not break Codex on tool failure.
        log_result(None, None, False, f"gate unavailable: {exc}")
        return 0

    score = int(result.get("score", 100))
    band = str(result.get("band", "unknown"))
    floor = threshold()

    if score >= floor:
        log_result(score, band, False)
        return 0

    advice = result.get("advice") or []
    advice_text = "; ".join(str(item) for item in advice[:4])
    reason = (
        f"slop-guard scored the drafted response {score}/100 ({band}), below the "
        f"required threshold {floor}. Rewrite the final answer before sending it. "
        "Keep concrete facts, remove filler, avoid stock AI phrasing, reduce list-heavy "
        "structure when prose is clearer, and preserve all technical claims. "
        f"Top advice: {advice_text}"
    )
    log_result(score, band, True, "below threshold")
    respond({"decision": "block", "reason": reason})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
