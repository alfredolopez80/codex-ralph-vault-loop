from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOP = ROOT / ".codex" / "hooks" / "stop_dispatch.py"
POST = ROOT / ".codex" / "hooks" / "post_tool_dispatch.py"
if str(ROOT / ".codex" / "hooks") not in sys.path:
    sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

import post_tool_dispatch
import stop_dispatch
from shared.persistence_metrics import WriteAccumulator
from shared.runtime_observability import normalize_event
from shared.stop_persistence import terminal_business_claim
from shared.stop_scope import scope_from_payload


def env_for(tmp_path: Path, *, mode: str = "stable") -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_HOME": str(tmp_path / "ralph"),
            "CODEX_MEMORY_HOME": str(tmp_path / "empty-memory"),
            "VAULT_DIR": str(tmp_path / "empty-vault"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "CODEX_HOOK_STATE_ROOT": str(tmp_path / "hook-state"),
            "CODEX_SLOP_GUARD_ENABLED": "0",
            "RALPH_RUNTIME_OBSERVABILITY_MODE": mode,
        }
    )
    return env


def stop_payload(tmp_path: Path, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "hook_event_name": "Stop",
        "cwd": str(tmp_path),
        "session_id": "stop-noop-session",
        "turn_id": "turn-1",
        "task_signature": "stop-noop-task",
        "branch": "feature-stop-noop",
        "sha": "abc123def456",
        "last_assistant_message": "The bounded local task is complete.",
    }
    payload.update(extra)
    return payload


def run_stop(tmp_path: Path, payload: dict[str, object], *, mode: str = "stable") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STOP)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env_for(tmp_path, mode=mode),
        check=False,
        timeout=20,
    )


def tree_snapshot(root: Path, *, exclude_observability: bool = True) -> dict[str, tuple[str, int, int]]:
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[str, int, int]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if exclude_observability and ("observability/runtime-events" in relative or relative.endswith("/runtime-events.jsonl")):
            continue
        data = path.read_bytes()
        stat = path.stat()
        snapshot[relative] = (hashlib.sha256(data).hexdigest(), len(data), stat.st_mtime_ns)
    return snapshot


def jsonl_files(root: Path, name: str) -> list[Path]:
    return sorted(path for path in root.rglob(name) if path.is_file()) if root.exists() else []


def test_identical_successful_stop_is_business_physical_noop(tmp_path: Path) -> None:
    event = stop_payload(tmp_path)
    first = run_stop(tmp_path, event)
    assert first.returncode == 0 and first.stdout == ""
    before = tree_snapshot(tmp_path / "ralph")

    second = run_stop(tmp_path, event)
    assert second.returncode == 0 and second.stdout == ""
    after = tree_snapshot(tmp_path / "ralph")

    assert after == before
    assert len(jsonl_files(tmp_path / "ralph", "stop-events.jsonl")) == 1
    assert len(jsonl_files(tmp_path / "ralph", "runtime-events.jsonl")) == 1


def test_identical_failed_stop_keeps_continuation_contract_without_business_rewrite(tmp_path: Path) -> None:
    event = stop_payload(tmp_path, tests_failed=True, evidence_fingerprint="failure-a")
    first = run_stop(tmp_path, event)
    assert first.returncode == 0
    first_body = json.loads(first.stdout)
    assert first_body["decision"] == "block"
    before = tree_snapshot(tmp_path / "ralph")

    second = run_stop(tmp_path, event)
    assert second.returncode == 0 and second.stdout == ""
    after = tree_snapshot(tmp_path / "ralph")

    assert after == before
    continuation = next((tmp_path / "ralph").rglob("continuation.json"))
    assert json.loads(continuation.read_text(encoding="utf-8"))["entries"]
    assert len(jsonl_files(tmp_path / "ralph", "stop-events.jsonl")) == 1


def test_changed_critical_evidence_is_a_distinct_business_operation(tmp_path: Path) -> None:
    first_payload = stop_payload(tmp_path, tests_failed=True, critical=True, evidence_fingerprint="failure-a")
    assert json.loads(run_stop(tmp_path, first_payload).stdout)["decision"] == "block"
    second_payload = dict(first_payload)
    second_payload["evidence_fingerprint"] = "failure-b"
    second = run_stop(tmp_path, second_payload)
    assert json.loads(second.stdout)["decision"] == "block"

    events = next((tmp_path / "ralph").rglob("stop-events.jsonl"))
    assert len(events.read_text(encoding="utf-8").splitlines()) == 2
    continuation = next((tmp_path / "ralph").rglob("continuation.json"))
    state = json.loads(continuation.read_text(encoding="utf-8"))
    assert next(iter(state["entries"].values()))["count"] == 2


def test_commit_or_generation_change_is_distinct_and_enqueues_once_per_generation(tmp_path: Path) -> None:
    first_payload = stop_payload(tmp_path, generation="generation-a")
    assert run_stop(tmp_path, first_payload).returncode == 0
    marker = next((tmp_path / "ralph").rglob("terminal-business.json"))
    first_fingerprint = next(iter(json.loads(marker.read_text(encoding="utf-8"))["entries"].values()))["fingerprint"]
    second_payload = dict(first_payload)
    second_payload.update({"sha": "def789abc012", "generation": "generation-b"})
    assert run_stop(tmp_path, second_payload).returncode == 0

    second_fingerprint = next(iter(json.loads(marker.read_text(encoding="utf-8"))["entries"].values()))["fingerprint"]
    assert second_fingerprint != first_fingerprint
    stop_events = next((tmp_path / "ralph").rglob("stop-events.jsonl"))
    assert len(stop_events.read_text(encoding="utf-8").splitlines()) == 2
    queue = next((tmp_path / "ralph").rglob("queue.json"))
    assert len(json.loads(queue.read_text(encoding="utf-8"))["jobs"]) == 2


def test_malformed_terminal_marker_is_preserved_for_explicit_recovery(tmp_path: Path) -> None:
    event = stop_payload(tmp_path)
    first = run_stop(tmp_path, event)
    assert first.returncode == 0 and first.stdout == ""
    marker = next((tmp_path / "ralph").rglob("terminal-business.json"))
    marker.write_bytes(b"not-json")
    before = marker.read_bytes()

    second = run_stop(tmp_path, event)

    assert second.returncode == 0 and second.stdout == ""
    assert marker.read_bytes() == before


def test_terminal_claim_retention_keeps_new_scope_even_when_key_sorts_low(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    base = stop_payload(tmp_path)

    def claim_scope(task: str) -> str:
        scope = scope_from_payload({**base, "task_signature": task})
        with terminal_business_claim(scope, f"{len(task):064x}") as claim:
            assert claim.available and not claim.duplicate
            claim.commit()
        return scope.scope_key

    existing_keys = {claim_scope(f"retained-{index}") for index in range(256)}
    marker = next((tmp_path / "ralph").rglob("terminal-business.json"))
    current_keys = set(json.loads(marker.read_text(encoding="utf-8"))["entries"])
    assert current_keys == existing_keys
    minimum = min(current_keys)
    candidate = next(
        f"retained-candidate-{index}"
        for index in range(10_000)
        if scope_from_payload({**base, "task_signature": f"retained-candidate-{index}"}).scope_key < minimum
    )
    candidate_key = claim_scope(candidate)

    entries = json.loads(marker.read_text(encoding="utf-8"))["entries"]
    assert candidate_key in entries
    assert len(entries) == 256


def test_changed_validation_result_is_a_distinct_business_operation(tmp_path: Path) -> None:
    first_payload = stop_payload(tmp_path, validation_status="pass")
    assert run_stop(tmp_path, first_payload).returncode == 0
    second_payload = dict(first_payload)
    second_payload["validation_status"] = "partial"
    assert run_stop(tmp_path, second_payload).returncode == 0

    stop_events = next((tmp_path / "ralph").rglob("stop-events.jsonl"))
    assert len(stop_events.read_text(encoding="utf-8").splitlines()) == 2


def test_concurrent_identical_stops_publish_one_business_event(tmp_path: Path) -> None:
    event = stop_payload(tmp_path)

    def invoke(_: int) -> subprocess.CompletedProcess[str]:
        return run_stop(tmp_path, event)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(invoke, range(6)))
    assert all(result.returncode == 0 and result.stdout == "" for result in results)
    stop_events = next((tmp_path / "ralph").rglob("stop-events.jsonl"))
    assert len(stop_events.read_text(encoding="utf-8").splitlines()) == 1
    queue = next((tmp_path / "ralph").rglob("queue.json"))
    assert len(json.loads(queue.read_text(encoding="utf-8"))["jobs"]) == 1


def test_benchmark_mode_records_duplicate_observation_but_not_business_state(tmp_path: Path) -> None:
    event = stop_payload(tmp_path)
    assert run_stop(tmp_path, event, mode="benchmark").returncode == 0
    before = tree_snapshot(tmp_path / "ralph")
    assert run_stop(tmp_path, event, mode="benchmark").returncode == 0
    after = tree_snapshot(tmp_path / "ralph")
    assert after == before
    runtime_events = next((tmp_path / "ralph").rglob("runtime-events.jsonl"))
    assert len(runtime_events.read_text(encoding="utf-8").splitlines()) == 2


def test_stop_safety_gate_still_blocks_even_when_business_state_is_unchanged(tmp_path: Path) -> None:
    event = stop_payload(tmp_path, safety_failure=True, critical=True, evidence_fingerprint="safety-a")
    first = run_stop(tmp_path, event)
    assert json.loads(first.stdout)["decision"] == "block"
    before = tree_snapshot(tmp_path / "ralph")
    second = run_stop(tmp_path, event)
    # The second identical hard finding follows the existing bounded
    # continuation contract and allows Stop; the finding was still evaluated
    # and the first response remains the safety proof.
    assert second.stdout == ""
    assert tree_snapshot(tmp_path / "ralph") == before


def test_normal_dispatch_does_not_call_recursive_scans(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RALPH_HOME", str(tmp_path / "ralph"))
    monkeypatch.setenv("CODEX_MEMORY_HOME", str(tmp_path / "empty-memory"))
    monkeypatch.setenv("RALPH_LOCAL_NOTES_ROOTS", "")
    monkeypatch.setenv("CODEX_HOOK_STATE_ROOT", str(tmp_path / "hook-state"))

    def fail_scan(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("recursive runtime scan must be benchmark-only")

    monkeypatch.setattr(post_tool_dispatch, "directory_bytes", fail_scan)
    monkeypatch.setattr(stop_dispatch, "directory_bytes", fail_scan)
    post = {
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "session_id": "scan-session",
        "turn_id": "scan-turn",
        "tool_use_id": "scan-tool",
        "tool_name": "exec_command",
        "tool_input": {"cmd": "git status --short"},
        "tool_response": {"exit_code": 0, "stdout": "ok"},
        "success": True,
    }
    assert post_tool_dispatch.dispatch(post) is None
    original_parse = stop_dispatch.parse_payload
    monkeypatch.setattr(stop_dispatch, "parse_payload", lambda: stop_payload(tmp_path))
    try:
        assert stop_dispatch.main() == 0
    finally:
        monkeypatch.setattr(stop_dispatch, "parse_payload", original_parse)


def test_writer_reported_bytes_are_present_and_unknown_is_not_zero(tmp_path: Path) -> None:
    event = {
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "session_id": "writer-session",
        "turn_id": "writer-turn",
        "tool_use_id": "writer-tool",
        "tool_name": "exec_command",
        "tool_input": {"cmd": "printf changed"},
        "tool_response": {"exit_code": 0, "stdout": "ok"},
        "success": True,
    }
    monkeypatch_env = env_for(tmp_path)
    result = subprocess.run(
        [sys.executable, str(POST)],
        cwd=ROOT,
        input=json.dumps(event),
        text=True,
        capture_output=True,
        env=monkeypatch_env,
        check=False,
    )
    assert result.returncode == 0
    runtime = next((tmp_path / "ralph").rglob("runtime-events.jsonl"))
    record = json.loads(runtime.read_text(encoding="utf-8").splitlines()[0])
    assert record["persistence_bytes_known"] is True
    assert record["persistence_bytes"] > 0

    aggregate = WriteAccumulator()
    aggregate.add(None)
    assert aggregate.bytes_written is None
    normalized = normalize_event(
        {
            "event": "stop",
            "project_id": "p-0123456789abcdef",
            "persistence_bytes": None,
            "persistence_bytes_known": False,
        }
    )
    assert normalized is not None
    assert normalized["persistence_bytes"] is None
    assert normalized["persistence_bytes_known"] is False
