#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys

from shared.paths import REPO_ROOT, ensure_runtime, read_hook_input, write_json


def run_assisted_promotion() -> None:
    script = REPO_ROOT / "scripts" / "memory" / "dream.py"
    if not script.exists():
        return
    subprocess.run(
        [sys.executable, str(script), "--auto-update-state", "--assist-promote"],
        text=True,
        capture_output=True,
        check=False,
        timeout=12,
        env=os.environ.copy(),
    )


def promotion_summary() -> dict[str, object]:
    root = ensure_runtime()
    path = root / "reports" / "memory" / "promotion-latest.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    payload = read_hook_input()
    if payload.get("stop_hook_active"):
        return 0
    run_assisted_promotion()
    summary = promotion_summary()
    review = summary.get("review_requested")
    if not isinstance(review, list) or not review:
        return 0
    preview = []
    for item in review[:3]:
        if isinstance(item, dict):
            preview.append(f"{item.get('target_layer', '?')} {float(item.get('confidence', 0.0)):.2f}: {item.get('text', '')}")
    reason = "Ralph Memory found promotion candidates that need review before becoming canonical: " + " | ".join(preview)
    write_json({"decision": "warn", "reason": reason})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
