#!/usr/bin/env python3
"""Explicit, bounded runner for deferred memory maintenance jobs.

This command is intentionally outside interactive hooks.  It invokes the
existing dream scheduler as the source of truth for promotion and vault review
decisions, while the queue provides at-least-once delivery and deduplication.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parents[2] / ".codex" / "hooks"
REPO_ROOT = HOOKS_DIR.parent.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from shared.maintenance_queue import (  # noqa: E402
    MaintenanceJob,
    append_runner_event,
    claim_jobs,
    complete_job,
    instance_lock,
    queued_project_ids,
)
from shared.runtime_observability import record_event  # noqa: E402


def _safe_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _run_job(job: MaintenanceJob, *, max_seconds: int) -> tuple[bool, str, float, int]:
    scheduler = REPO_ROOT / "scripts" / "memory" / "dream-scheduler.py"
    if not scheduler.is_file():
        return False, "missing_scheduler", 0.0, 0
    started = time.perf_counter_ns()
    env = {
        **os.environ.copy(),
        "VAULT_PROJECT": job.project_slug,
        "RALPH_PROJECT_ID": job.project_id,
        "RALPH_MEMORY_PROJECT_ID": job.project_id,
        "RALPH_WORKSPACE_ROOT": job.workspace_root,
        "RALPH_SESSION_ID": job.session_id,
    }
    command = [
        sys.executable,
        str(scheduler),
        "--force",
        "--max-seconds",
        str(max_seconds),
        "--vault-project",
        job.project_slug,
        "--project-id",
        job.project_id,
        "--workspace-root",
        job.workspace_root,
    ]
    workspace = Path(job.workspace_root)
    cwd = workspace if workspace.is_dir() and not workspace.is_symlink() else REPO_ROOT
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=max_seconds * 2 + 5,
            env=env,
        )
    except subprocess.TimeoutExpired:
        runtime_ms = (time.perf_counter_ns() - started) / 1_000_000
        return False, "runner_timeout", runtime_ms, 1
    except (OSError, ValueError):
        runtime_ms = (time.perf_counter_ns() - started) / 1_000_000
        return False, "runner_spawn_failed", runtime_ms, 0
    runtime_ms = (time.perf_counter_ns() - started) / 1_000_000
    return result.returncode == 0, ("scheduler_failed" if result.returncode else ""), runtime_ms, 1


def _record_maintenance(project_id: str, summary: dict[str, object], started_ns: int) -> None:
    try:
        record_event(
            None,
            {"project_id": project_id},
            event="maintenance",
            dispatcher="run_pending_maintenance",
            duration_ns=time.perf_counter_ns() - started_ns,
            process_count=1,
            child_process_count=int(summary.get("child_process_count", 0) or 0),
            components_considered=["queue", "dream_scheduler", "vault_review"],
            components_executed=["queue"],
            components_skipped=["interactive_output"],
            skipped_reason=["deferred"],
            persistence_bytes=0,
            success=summary.get("status") == "completed",
            scenario="maintenance",
            maintenance_deferred=True,
        )
    except Exception:
        pass


def run(project_ids: list[str], *, max_jobs: int, max_seconds: int) -> dict[str, object]:
    started = time.perf_counter_ns()
    processed = 0
    succeeded = 0
    failed = 0
    child_processes = 0
    jobs_seen = 0
    with instance_lock() as locked:
        if not locked:
            summary = {
                "schema_version": 1,
                "status": "lock_unavailable",
                "processed_jobs": 0,
                "succeeded_jobs": 0,
                "failed_jobs": 0,
                "child_process_count": 0,
                "runner_runtime_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
            }
            for project_id in project_ids:
                _record_maintenance(project_id, summary, started)
            return summary
        for project_id in project_ids:
            if processed >= max_jobs:
                break
            jobs = claim_jobs(project_id, limit=max_jobs - processed)
            jobs_seen += len(jobs)
            for job in jobs:
                if processed >= max_jobs:
                    break
                ok, error_code, runtime_ms, children = _run_job(job, max_seconds=max_seconds)
                child_processes += children
                complete_job(project_id, job.job_id, success=ok, error_code=error_code)
                append_runner_event(
                    project_id=project_id,
                    event="job_completed" if ok else "job_failed",
                    job_id=job.job_id,
                    runtime_ms=runtime_ms,
                    error_code=error_code,
                )
                processed += 1
                if ok:
                    succeeded += 1
                else:
                    failed += 1
    summary = {
        "schema_version": 1,
        "status": "completed",
        "project_count": len(project_ids),
        "jobs_seen": jobs_seen,
        "processed_jobs": processed,
        "succeeded_jobs": succeeded,
        "failed_jobs": failed,
        "child_process_count": child_processes,
        "runner_runtime_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
    }
    for project_id in project_ids:
        _record_maintenance(project_id, summary, started)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Process deferred Ralph memory maintenance jobs.")
    parser.add_argument("--project-id", action="append", default=[], help="Project ID to process; repeatable.")
    parser.add_argument("--all", action="store_true", help="Process all project queues under RALPH_HOME.")
    parser.add_argument("--max-jobs", default="8")
    parser.add_argument("--max-seconds", default="15")
    parser.add_argument("--json", action="store_true", help="Emit a sanitized runner summary.")
    args = parser.parse_args()
    project_ids = list(dict.fromkeys(args.project_id))
    if args.all or not project_ids:
        project_ids = queued_project_ids() if not project_ids else project_ids
    summary = run(
        project_ids,
        max_jobs=_safe_int(args.max_jobs, 8, 1, 64),
        max_seconds=_safe_int(args.max_seconds, 15, 1, 60),
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
