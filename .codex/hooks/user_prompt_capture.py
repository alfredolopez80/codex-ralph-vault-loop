#!/usr/bin/env python3
from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import time
from contextlib import redirect_stdout

from shared.active_context import ActiveContext, active_context_from_payload, hash_text, project_runtime_root
from shared.context_budget import classify_prompt
from shared.paths import REPO_ROOT, append_jsonl, now_iso, read_hook_input, write_json
from shared.redaction import is_red
from shared.runtime_budget import child_timeout_for
from shared.runtime_observability import record_event

TASK_INTAKE_TIMEOUT_SECONDS = child_timeout_for("UserPromptSubmit", "user_prompt_capture")


def capture_safe_prompt(prompt: str, context: ActiveContext) -> None:
    try:
        root = project_runtime_root(context)
        append_jsonl(
            root / "ledgers" / "user-prompts.jsonl",
            {
                "created_at": now_iso(),
                "event": "UserPromptSubmit",
                "prompt_hash": hash_text(prompt),
                "project_id": context.project_id,
                "project": context.project_slug,
                "session_id": context.session_id,
                "workspace_instance_id": context.workspace_instance_id,
            },
        )
    except Exception:
        return


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


def _capture_main(payload: dict, context: ActiveContext | None = None) -> int:
    context = context or active_context_from_payload(payload, resolve_git=False)
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


def main() -> int:
    started = time.perf_counter_ns()
    payload = read_hook_input()
    try:
        context = active_context_from_payload(payload, resolve_git=False)
    except Exception:
        context = None
    output = io.StringIO()
    with redirect_stdout(output):
        result = _capture_main(payload, context)
    rendered = output.getvalue()
    if rendered:
        sys.stdout.write(rendered)
    try:
        intake_path = REPO_ROOT / "scripts" / "memory" / "task-intake.py"
        if context is not None:
            has_prompt = isinstance(payload.get("prompt") or payload.get("user_prompt"), str) and bool((payload.get("prompt") or payload.get("user_prompt")).strip())
            record_event(
                context,
                payload,
                event="user_prompt",
                dispatcher="user_prompt_capture",
                duration_ns=time.perf_counter_ns() - started,
                process_count=1,
                child_process_count=1 if intake_path.exists() and has_prompt else 0,
                components_considered=["prompt_capture", "task_intake"],
                components_executed=["prompt_capture" if isinstance(payload.get("prompt") or payload.get("user_prompt"), str) else "none"],
                components_skipped=[],
                skipped_reason=[],
                output_bytes=len(rendered.encode("utf-8")),
                success=True,
                scenario=payload.get("scenario"),
            )
    except Exception:
        pass
    return result


if __name__ == "__main__":
    raise SystemExit(main())
