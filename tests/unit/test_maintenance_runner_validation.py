from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import active_context_from_payload
from shared.maintenance_queue import MaintenanceJob

SCRIPT = ROOT / "scripts" / "memory" / "run-pending-maintenance.py"
SPEC = importlib.util.spec_from_file_location("pending_maintenance_runner", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _job(tmp_path: Path) -> MaintenanceJob:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = active_context_from_payload(
        {"cwd": str(workspace), "session_id": "runner-validation"},
        resolve_git=False,
    )
    return MaintenanceJob(
        job_id="job-fixture",
        operation="dream_and_vault_review",
        project_id=context.project_id,
        project_slug=context.project_slug,
        workspace_root=str(workspace),
        workspace_instance_id=context.workspace_instance_id,
        session_id=context.session_id,
        branch=context.branch,
        sha=context.sha,
        source_generation="generation",
        reason_code="test",
        policy_version="maintenance-v1",
        created_at="2026-08-09T00:00:00+00:00",
        updated_at="2026-08-09T00:00:00+00:00",
        status="leased",
        attempts=1,
        max_attempts=3,
        next_attempt_at=0,
        lease_until=0,
        last_error_code="",
    )


def test_runner_rejects_forged_descriptor_without_spawning(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    forged_root = tmp_path / "forged"
    forged_root.mkdir()
    forged = replace(_job(tmp_path), workspace_root=str(forged_root))
    calls = {"children": 0}
    monkeypatch.setattr(runner, "claim_jobs", lambda *_args, **_kwargs: [forged])
    monkeypatch.setattr(
        runner,
        "_run_job",
        lambda *_args, **_kwargs: calls.__setitem__("children", calls["children"] + 1),
    )
    monkeypatch.setattr(runner, "complete_job", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "append_runner_event", lambda **_kwargs: True)
    monkeypatch.setattr(runner, "_record_maintenance", lambda *_args, **_kwargs: None)
    summary = runner.run([forged.project_id], max_jobs=1, max_seconds=1)
    assert calls["children"] == 0
    assert summary["failed_jobs"] == 1
    assert summary["child_process_count"] == 0
