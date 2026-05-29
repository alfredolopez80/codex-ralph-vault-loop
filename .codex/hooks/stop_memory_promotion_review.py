#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys

from shared.active_context import ActiveContext, active_context_from_payload, project_runtime_root
from shared.paths import REPO_ROOT, read_hook_input


def run_assisted_promotion(context: ActiveContext) -> None:
    script = REPO_ROOT / "scripts" / "memory" / "dream.py"
    if not script.exists():
        return
    timeout = int(os.environ.get("RALPH_PROMOTION_TIMEOUT_SECONDS", "12"))
    env = {
        **os.environ.copy(),
        "VAULT_PROJECT": context.project_slug,
        "RALPH_PROJECT_ID": context.project_id,
        "RALPH_WORKSPACE_ROOT": str(context.workspace_root),
        "RALPH_SESSION_ID": context.session_id,
    }
    try:
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--auto-update-state",
                "--assist-promote",
                "--vault-project",
                context.project_slug,
                "--project-id",
                context.project_id,
                "--workspace-root",
                str(context.workspace_root),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except Exception:
        return


def run_vault_inbox_review(context: ActiveContext) -> None:
    if os.environ.get("RALPH_VAULT_INBOX_REVIEW", "1").lower() in {"0", "false", "no"}:
        return
    script = REPO_ROOT / "scripts" / "vault" / "vault-inbox-review.py"
    if not script.exists():
        return
    timeout = int(os.environ.get("RALPH_VAULT_REVIEW_TIMEOUT_SECONDS", "5"))
    project = context.project_slug
    env = {
        **os.environ.copy(),
        "VAULT_PROJECT": context.project_slug,
        "RALPH_PROJECT_ID": context.project_id,
        "RALPH_WORKSPACE_ROOT": str(context.workspace_root),
        "RALPH_SESSION_ID": context.session_id,
    }
    try:
        subprocess.run(
            [sys.executable, str(script), "--project", project],
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except Exception:
        return


def promotion_summary(context: ActiveContext) -> dict[str, object]:
    root = project_runtime_root(context)
    path = root / "reports" / "memory" / "promotion-latest.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def vault_review_summary(context: ActiveContext) -> dict[str, object]:
    root = project_runtime_root(context)
    path = root / "reports" / "vault-inbox-review" / "latest.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    try:
        payload = read_hook_input()
        context = active_context_from_payload(payload)
        if payload.get("stop_hook_active"):
            return 0
        run_assisted_promotion(context)
        run_vault_inbox_review(context)
        summary = promotion_summary(context)
        vault_review = vault_review_summary(context)
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
    except Exception:
        return 0
    if not warnings:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
