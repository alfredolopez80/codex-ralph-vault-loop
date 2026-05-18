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
    timeout = int(os.environ.get("RALPH_PROMOTION_TIMEOUT_SECONDS", "12"))
    subprocess.run(
        [sys.executable, str(script), "--auto-update-state", "--assist-promote"],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=os.environ.copy(),
    )


def run_vault_inbox_review() -> None:
    if os.environ.get("RALPH_VAULT_INBOX_REVIEW", "1").lower() in {"0", "false", "no"}:
        return
    script = REPO_ROOT / "scripts" / "vault" / "vault-inbox-review.py"
    if not script.exists():
        return
    timeout = int(os.environ.get("RALPH_VAULT_REVIEW_TIMEOUT_SECONDS", "5"))
    project = os.environ.get("VAULT_PROJECT") or REPO_ROOT.name
    try:
        subprocess.run(
            [sys.executable, str(script), "--project", project],
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except Exception:
        return


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


def vault_review_summary() -> dict[str, object]:
    root = ensure_runtime()
    path = root / "reports" / "vault-inbox-review" / "latest.json"
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
    run_vault_inbox_review()
    summary = promotion_summary()
    vault_review = vault_review_summary()
    warnings = []
    review = summary.get("review_requested")
    if isinstance(review, list) and review:
        preview = []
        for item in review[:3]:
            if isinstance(item, dict):
                preview.append(f"{item.get('target_layer', '?')} {float(item.get('confidence', 0.0)):.2f}: {item.get('text', '')}")
        warnings.append("Ralph Memory found promotion candidates that need review before becoming canonical: " + " | ".join(preview))
    ask_user = int(vault_review.get("ask_user") or 0)
    if ask_user:
        warnings.append(f"GRADUATION_REVIEW_REQUIRED count={ask_user}: MiVault inbox has ambiguous or global candidates.")
    if not warnings:
        return 0
    reason = " | ".join(warnings)
    write_json({"decision": "warn", "reason": reason})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
