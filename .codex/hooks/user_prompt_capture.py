#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys

from shared.paths import REPO_ROOT, append_jsonl, ensure_runtime, now_iso, read_hook_input
from shared.redaction import is_red, safe_preview


TASK_INTAKE_TIMEOUT_SECONDS = 12


def capture_safe_prompt(prompt: str) -> None:
    try:
        root = ensure_runtime()
        append_jsonl(
            root / "ledgers" / "user-prompts.jsonl",
            {
                "created_at": now_iso(),
                "event": "UserPromptSubmit",
                "prompt": safe_preview(prompt),
            },
        )
    except Exception:
        print("RALPH_USER_PROMPT_CAPTURE_STATUS=failed")


def run_task_intake(payload: dict) -> None:
    task_intake = REPO_ROOT / "scripts" / "memory" / "task-intake.py"
    if not task_intake.exists():
        return
    try:
        result = subprocess.run(
            [sys.executable, str(task_intake)],
            input=json.dumps(payload, ensure_ascii=True),
            text=True,
            capture_output=True,
            check=False,
            timeout=TASK_INTAKE_TIMEOUT_SECONDS,
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
    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    if not is_red(prompt):
        capture_safe_prompt(prompt)
    run_task_intake(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
