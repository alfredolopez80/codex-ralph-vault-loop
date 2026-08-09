from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.active_context import active_context_from_payload  # noqa: E402
from shared.maintenance_queue import (  # noqa: E402
    claim_jobs,
    complete_job,
    enqueue_maintenance,
    queue_path,
    validate_job_descriptor,
)


def context_for(tmp_path: Path, *, branch: str = "main"):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    context = active_context_from_payload({"cwd": str(workspace), "session_id": "session-a"})
    return replace(context, branch=branch, sha="abc123")


def test_enqueue_is_idempotent_and_descriptor_has_no_raw_content(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context = context_for(tmp_path)
    payload = {
        "prompt": "RAW_PROMPT_SENTINEL",
        "memory_candidates": [{"text": "RAW_MEMORY_SENTINEL"}],
        "selected_memory_ids": ["sentinel-memory-id"],
        "memory_generation": "generation-1",
    }
    first = enqueue_maintenance(context, reason_code="stop", payload=payload)
    second = enqueue_maintenance(context, reason_code="stop", payload=payload)
    assert first.accepted is True
    assert second.deduplicated is True
    text = queue_path(context.project_id).read_text(encoding="utf-8")
    assert "RAW_PROMPT_SENTINEL" not in text
    assert "RAW_MEMORY_SENTINEL" not in text
    assert "sentinel-memory-id" not in text
    assert text.count('"job_id"') == 1


def test_generation_change_bypasses_debounce_and_creates_new_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context = context_for(tmp_path)
    first = enqueue_maintenance(context, reason_code="stop", payload={"memory_generation": "one"})
    second = enqueue_maintenance(context, reason_code="stop", payload={"memory_generation": "two"})
    assert first.accepted and second.accepted
    state = json.loads(queue_path(context.project_id).read_text(encoding="utf-8"))
    assert len(state["jobs"]) == 2


def test_expired_final_lease_is_dead_lettered_instead_of_reclaimed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setenv("RALPH_MAINTENANCE_MAX_ATTEMPTS", "1")
    context = context_for(tmp_path)
    result = enqueue_maintenance(context, reason_code="stop")
    path = queue_path(context.project_id)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["jobs"][0].update({"status": "leased", "attempts": 1, "lease_until": 0})
    path.write_text(json.dumps(state), encoding="utf-8")
    assert claim_jobs(context.project_id) == []
    recovered = json.loads(path.read_text(encoding="utf-8"))["jobs"][0]
    assert recovered["status"] == "dead_lettered"
    assert recovered["last_error_code"] == "lease_attempts_exhausted"


def test_descriptor_validation_rejects_forged_workspace_and_stale_head(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context = active_context_from_payload({"cwd": str(ROOT), "session_id": "maintenance-current-repo"})
    enqueue_maintenance(context, reason_code="stop")
    job = claim_jobs(context.project_id)[0]
    assert validate_job_descriptor(job) == ""
    assert validate_job_descriptor(replace(job, sha="deadbeefdeadbeef")) == "stale_head"
    forged = replace(job, workspace_root=str(tmp_path / "other"))
    (tmp_path / "other").mkdir()
    assert validate_job_descriptor(forged) == "workspace_identity_mismatch"


def test_branch_change_does_not_share_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    first_context = context_for(tmp_path, branch="feature-a")
    second_context = replace(first_context, branch="feature-b")
    first = enqueue_maintenance(first_context, reason_code="stop", payload={"memory_generation": "same"})
    second = enqueue_maintenance(second_context, reason_code="stop", payload={"memory_generation": "same"})
    assert first.accepted and second.accepted and first.job_id != second.job_id


def test_corrupt_queue_is_quarantined_and_recovered(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context = context_for(tmp_path)
    path = queue_path(context.project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    result = enqueue_maintenance(context, reason_code="session_start")
    assert result.accepted
    assert list(path.parent.glob("queue.invalid.*.json"))
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_claim_retry_and_dead_letter_are_bounded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setenv("RALPH_MAINTENANCE_MAX_ATTEMPTS", "1")
    context = context_for(tmp_path)
    result = enqueue_maintenance(context, reason_code="stop")
    claimed = claim_jobs(context.project_id)
    assert len(claimed) == 1 and claimed[0].job_id == result.job_id
    assert complete_job(context.project_id, result.job_id, success=False, error_code="fixture_failure")
    state = json.loads(queue_path(context.project_id).read_text(encoding="utf-8"))
    assert state["jobs"][0]["status"] == "dead_lettered"
    assert "fixture_failure" == state["jobs"][0]["last_error_code"]


def test_concurrent_enqueue_keeps_one_descriptor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context = context_for(tmp_path)

    def enqueue() -> object:
        return enqueue_maintenance(context, reason_code="session_start", payload={"memory_generation": "same"})

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: enqueue(), range(12)))
    assert sum(bool(result.accepted) for result in results) == 1
    state = json.loads(queue_path(context.project_id).read_text(encoding="utf-8"))
    assert len(state["jobs"]) == 1


def test_symlink_escape_fails_open(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "ralph"
    monkeypatch.setenv("RALPH_HOME", str(runtime))
    context = context_for(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    project_dir = runtime / "projects" / context.project_id
    project_dir.mkdir(parents=True)
    (project_dir / "maintenance").symlink_to(outside, target_is_directory=True)
    result = enqueue_maintenance(context, reason_code="stop")
    assert result.accepted is False
    assert not list(outside.iterdir())


def test_project_identifier_cannot_escape_queue_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context = context_for(tmp_path)
    unsafe = replace(context, project_id="../../outside")
    result = enqueue_maintenance(unsafe, reason_code="stop")
    assert result.accepted
    assert result.path is not None
    assert result.path.is_relative_to(tmp_path / "ralph")
    assert not (tmp_path / "outside" / "maintenance").exists()


def test_queue_and_parent_runtime_are_private(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    context = context_for(tmp_path)
    result = enqueue_maintenance(context, reason_code="stop")
    assert result.accepted and result.path is not None
    assert result.path.stat().st_mode & 0o777 == 0o600
    assert result.path.parent.stat().st_mode & 0o777 == 0o700
    assert result.path.parent.parent.stat().st_mode & 0o777 == 0o700


def test_ttl_evicts_old_jobs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setenv("RALPH_MAINTENANCE_TTL_SECONDS", "60")
    context = context_for(tmp_path)
    path = queue_path(context.project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {
        "schema_version": 1,
        "updated_at": "2000-01-01T00:00:00+00:00",
        "jobs": [{"job_id": "old", "created_epoch": 1, "updated_epoch": 1, "status": "pending"}],
    }
    path.write_text(json.dumps(old), encoding="utf-8")
    result = enqueue_maintenance(context, reason_code="stop")
    assert result.accepted
    state = json.loads(path.read_text(encoding="utf-8"))
    assert [job["job_id"] for job in state["jobs"]] == [result.job_id]


def test_max_entries_eviction_is_bounded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setenv("RALPH_MAINTENANCE_MAX_ENTRIES", "2")
    monkeypatch.setenv("RALPH_MAINTENANCE_DEBOUNCE_SECONDS", "0")
    context = context_for(tmp_path)
    for index in range(4):
        assert enqueue_maintenance(context, reason_code="stop", payload={"memory_generation": str(index)}).accepted
    state = json.loads(queue_path(context.project_id).read_text(encoding="utf-8"))
    assert len(state["jobs"]) == 2
