#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys

from shared.active_context import ActiveContext, active_context_from_payload, hash_text, project_runtime_root
from shared.context_budget import classify_prompt
from shared.paths import REPO_ROOT, append_jsonl, now_iso, read_hook_input, write_json
from shared.redaction import is_red


TASK_INTAKE_TIMEOUT_SECONDS = 12


def prompt_terms(prompt: str) -> list[str]:
    terms: list[str] = []
    for raw in prompt.replace("/", " ").replace("-", " ").split():
        value = "".join(char for char in raw.lower() if char.isalnum() or char in "._")
        if len(value) >= 4 and value not in terms:
            terms.append(value)
        if len(terms) >= 12:
            break
    return terms


def capture_safe_prompt(prompt: str, context: ActiveContext) -> None:
    try:
        root = project_runtime_root(context)
        append_jsonl(
            root / "ledgers" / "user-prompts.jsonl",
            {
                "created_at": now_iso(),
                "event": "UserPromptSubmit",
                "prompt_hash": hash_text(prompt),
                "prompt_terms": prompt_terms(prompt),
                "project_id": context.project_id,
                "project": context.project_slug,
                "session_id": context.session_id,
                "workspace_root": str(context.workspace_root),
            },
        )
    except Exception:
        print("RALPH_USER_PROMPT_CAPTURE_STATUS=failed")


def run_task_intake(payload: dict, context: ActiveContext) -> None:
    task_intake = REPO_ROOT / "scripts" / "memory" / "task-intake.py"
    if not task_intake.exists():
        print(f"RALPH_TASK_INTAKE_STATUS=missing path={task_intake}")
        return
    try:
        env = {
            **os.environ.copy(),
            "VAULT_PROJECT": context.project_slug,
            "RALPH_PROJECT_ID": context.project_id,
            "RALPH_WORKSPACE_ROOT": str(context.workspace_root),
            "RALPH_SESSION_ID": context.session_id,
            "RALPH_BRANCH": context.branch,
        }
        result = subprocess.run(
            [
                sys.executable,
                str(task_intake),
                "--project",
                context.project_slug,
                "--project-id",
                context.project_id,
                "--workspace-root",
                str(context.workspace_root),
                "--branch",
                context.branch,
            ],
            input=json.dumps(payload, ensure_ascii=True),
            text=True,
            capture_output=True,
            check=False,
            timeout=TASK_INTAKE_TIMEOUT_SECONDS,
            env=env,
        )
    except Exception:
        print("RALPH_TASK_INTAKE_STATUS=failed")
        return
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print("RALPH_TASK_INTAKE_STATUS=failed")


def main() -> int:
    payload = read_hook_input()
    context = active_context_from_payload(payload)
    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    prompt_finding = classify_prompt(prompt)
    if prompt_finding:
        write_json(prompt_finding.hook_payload())
        return 0

    if not is_red(prompt):
        capture_safe_prompt(prompt, context)
    run_task_intake(payload, context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
