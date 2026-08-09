from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.implementation_store import (  # noqa: E402
    FutureSchemaError,
    IdempotencyError,
    ImplementationStore,
    IntegrityError,
    SchemaError,
    StoreIOError,
    StoreError,
    resolve_store_paths,
    state_size_band,
    validate_state,
)
from shared.implementation_store.schema import (  # noqa: E402
    STATE_HARD_LIMIT_BYTES,
    STATE_TARGET_BYTES,
    STATE_WARNING_BYTES,
    encoded_size,
    event_record_hash,
    new_state,
    validate_event,
)
from shared.implementation_store.io import publish_json  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def _store(tmp_path: Path) -> ImplementationStore:
    root = tmp_path / "primary" / "project"
    root.mkdir(parents=True)
    _git(root, "init")
    _git(root, "config", "user.name", "Store Test")
    _git(root, "config", "user.email", "store@example.invalid")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "fixture")
    return ImplementationStore(resolve_store_paths(primary_root=root))


def _business_snapshot(store: ImplementationStore, plan_id: str) -> dict[str, tuple[bytes, int, int, str] | None]:
    plan = store.plan_paths(plan_id)
    paths = {"state": plan.state, "events": plan.events, "manifest": store.paths.manifest}
    result: dict[str, tuple[bytes, int, int, str] | None] = {}
    for name, path in paths.items():
        if not path.exists():
            result[name] = None
            continue
        raw = path.read_bytes()
        result[name] = (raw, len(raw), path.stat().st_mtime_ns, hashlib.sha256(raw).hexdigest())
    return result


def _register(store: ImplementationStore, plan_id: str = "plan") -> None:
    store.register_plan(plan_id, now="2026-08-10T00:00:00+00:00")


def test_material_update_and_unchanged_retry_have_bounded_write_metadata(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)

    material = store.update_state("plan", {"phase": "build"}, kind="phase_changed", operation_id="op-material")
    retry_before = _business_snapshot(store, "plan")
    started = time.perf_counter()
    retry = store.update_state("plan", {"phase": "build"}, kind="phase_changed", operation_id="op-material")
    elapsed = time.perf_counter() - started

    assert material.changed
    assert material.metadata.appends <= 1
    assert material.metadata.replacements <= 1
    assert material.metadata.bytes_written > 0
    assert not retry.changed
    assert retry.metadata.bytes_written == 0
    assert retry.metadata.files_written == ()
    assert retry.metadata.appends == 0
    assert retry.metadata.replacements == 0
    assert _business_snapshot(store, "plan") == retry_before
    assert elapsed >= 0


def test_operation_id_is_plan_scoped_and_retry_ignores_later_incidental_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store, "one")
    _register(store, "two")
    store.update_state("one", {"phase": "build"}, kind="phase_changed", operation_id="shared-op")
    store.update_state("one", {"phase": "test"}, kind="phase_changed", operation_id="later-op")
    before_retry = _business_snapshot(store, "one")

    retry = store.update_state("one", {"phase": "build"}, kind="phase_changed", operation_id="shared-op")
    other_plan = store.update_state("two", {"phase": "build"}, kind="phase_changed", operation_id="shared-op")

    assert not retry.changed
    assert _business_snapshot(store, "one") == before_retry
    assert other_plan.changed
    assert len(store.read_events("one")) == 3
    assert len(store.read_events("two")) == 2


def test_conflicting_operation_id_is_blocking_without_mutation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)
    store.update_state("plan", {"phase": "build"}, kind="phase_changed", operation_id="op-conflict")
    before = _business_snapshot(store, "plan")

    with pytest.raises(IdempotencyError):
        store.update_state("plan", {"phase": "different"}, kind="phase_changed", operation_id="op-conflict")

    assert _business_snapshot(store, "plan") == before
    assert len(store.read_events("plan")) == 2


def test_git_ownership_and_progress_origin_are_validated_before_append(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(StoreError, match="different canonical repository"):
        store.register_plan(
            "wrong-repo",
            provenance={"git": {"repository_id": "repo-not-this-checkout"}},
        )
    _register(store)
    before = _business_snapshot(store, "plan")
    with pytest.raises(StoreError, match="origin or intent"):
        store.update_state(
            "plan",
            {"phase": "unsafe-origin"},
            kind="phase_changed",
            operation_id="op-origin",
            provenance={"origin": "engineering-task", "intent": "implementation"},
        )
    assert _business_snapshot(store, "plan") == before

    with pytest.raises(IntegrityError, match="different canonical repository"):
        store.update_state(
            "plan",
            {"git": {"branch": "other", "repository_id": "repo-other"}},
            kind="phase_changed",
            operation_id="op-git-update",
        )
    assert _business_snapshot(store, "plan") == before


def test_journal_from_another_repository_is_not_replayed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)
    events_path = store.plan_paths("plan").events
    event = json.loads(events_path.read_text(encoding="utf-8"))
    event["git"]["repository_id"] = "repo-foreign"
    event["record_hash"] = ""
    event["record_hash"] = event_record_hash(validate_event(event, expected_plan_id="plan", allow_unhashed=True))
    events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(IntegrityError, match="journal Git provenance"):
        store.read_events("plan")


def test_concurrent_distinct_operations_and_duplicate_retry_are_preserved(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)

    def distinct(index: int):
        return store.update_state("plan", {"phase": f"phase-{index}"}, kind="phase_changed", operation_id=f"op-{index}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        distinct_results = list(pool.map(distinct, range(6)))
    assert all(result.changed for result in distinct_results)
    assert [event["sequence"] for event in store.read_events("plan")] == list(range(1, 8))

    def duplicate(_index: int):
        return store.update_state("plan", {"phase": "duplicate"}, kind="phase_changed", operation_id="op-duplicate")

    with ThreadPoolExecutor(max_workers=6) as pool:
        duplicate_results = list(pool.map(duplicate, range(6)))
    assert sum(result.changed for result in duplicate_results) == 1
    assert len(store.read_events("plan")) == 8


def test_concurrent_conflicting_operation_id_has_one_winner(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)
    barrier = threading.Barrier(2)

    def write(phase: str):
        barrier.wait()
        try:
            return store.update_state("plan", {"phase": phase}, kind="phase_changed", operation_id="op-race")
        except IdempotencyError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["left", "right"]))
    assert sum(result != "conflict" for result in results) == 1
    assert results.count("conflict") == 1
    assert len([event for event in store.read_events("plan") if event["operation_id"] == "op-race"]) == 1


def test_append_failure_before_append_leaves_business_bytes_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    _register(store)
    before = _business_snapshot(store, "plan")
    import shared.implementation_store.store as store_module

    def fail(*_args, **_kwargs):
        raise StoreIOError("injected before append")

    monkeypatch.setattr(store_module, "append_jsonl", fail)
    with pytest.raises(StoreIOError, match="before append"):
        store.update_state("plan", {"phase": "blocked"}, kind="phase_changed", operation_id="op-before")
    assert _business_snapshot(store, "plan") == before


def test_append_then_snapshot_failure_replays_only_unapplied_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    _register(store)
    plan = store.plan_paths("plan")
    before_state = plan.state.read_bytes()
    import shared.implementation_store.store as store_module

    original_append = store_module.append_jsonl

    def append_then_fail(path: Path, payload, **kwargs):
        metadata = original_append(path, payload, **kwargs)
        if path == plan.events:
            raise StoreIOError("injected after append/fsync")
        return metadata

    monkeypatch.setattr(store_module, "append_jsonl", append_then_fail)
    with pytest.raises(StoreIOError, match="after append"):
        store.update_state(
            "plan",
            {"phase": "recovered", "objective": "exact semantic replay"},
            kind="phase_changed",
            operation_id="op-tail",
        )
    assert plan.state.read_bytes() == before_state
    assert len(store.read_events("plan")) == 2

    monkeypatch.setattr(store_module, "append_jsonl", original_append)
    retry = store.update_state(
        "plan",
        {"phase": "recovered", "objective": "exact semantic replay"},
        kind="phase_changed",
        operation_id="op-tail",
    )
    assert not retry.changed
    recovered = store.read_state("plan")
    assert recovered["phase"] == "recovered"
    assert recovered["objective"] == "exact semantic replay"
    assert recovered["last_event_sequence"] == 2
    assert recovered["last_event_hash"] == store.read_events("plan")[-1]["record_hash"]


def test_explicit_replay_rebuilds_missing_snapshot_from_verified_journal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)
    store.update_state(
        "plan",
        {"phase": "replay", "objective": "journal is authoritative"},
        kind="phase_changed",
        operation_id="op-replay",
    )
    expected = store.read_state("plan")
    state_path = store.plan_paths("plan").state
    state_path.unlink()

    replay = store.replay_plan("plan", now="2026-08-10T00:05:00+00:00")
    actual = store.read_state("plan")
    assert replay.changed
    assert actual["phase"] == expected["phase"]
    assert actual["objective"] == expected["objective"]
    assert actual["semantic_hash"] == expected["semantic_hash"]
    assert actual["last_event_sequence"] == expected["last_event_sequence"]


def test_snapshot_faults_preserve_append_and_allow_explicit_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    _register(store)
    plan = store.plan_paths("plan")
    import shared.implementation_store.io as io

    original_write_all = io._write_all
    write_calls = 0

    def fail_during_snapshot(fd: int, data: bytes) -> None:
        nonlocal write_calls
        write_calls += 1
        if write_calls == 2:
            raise StoreIOError("temp snapshot")
        original_write_all(fd, data)

    with monkeypatch.context() as patch:
        patch.setattr(io, "_write_all", fail_during_snapshot)
        with pytest.raises(StoreIOError) as fault:
            store.update_state("plan", {"phase": "temp-fault"}, kind="phase_changed", operation_id="op-temp")
        assert "temp snapshot" in str(fault.value.__cause__)
    assert len(store.read_events("plan")) == 2
    assert store.read_state("plan")["last_event_sequence"] == 1
    assert not list(plan.root.glob(".state.json.tmp-*"))

    original_fsync = io._fsync_directory

    def fsync_then_fail(path: Path):
        original_fsync(path)
        raise StoreIOError("after snapshot replace")

    with monkeypatch.context() as patch:
        patch.setattr(io, "_fsync_directory", fsync_then_fail)
        with pytest.raises(StoreIOError) as fault:
            store.update_state("plan", {"phase": "dir-fault"}, kind="phase_changed", operation_id="op-dir")
        assert "after snapshot replace" in str(fault.value.__cause__)
    assert plan.state.exists()
    # The first injected append is recoverable; the second operation has not
    # been allowed to publish a journal record when directory durability fails.
    assert len(store.read_events("plan")) == 3
    assert store.read_state("plan")["phase"] == "dir-fault"


def test_readers_ignore_partial_final_line_but_mutation_requires_repair(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)
    plan = store.plan_paths("plan")
    before = plan.events.read_bytes()
    plan.events.write_bytes(before + b'{"schema_version":1,"sequence":2')

    assert len(store.read_events("plan")) == 1
    with pytest.raises(IntegrityError, match="incomplete final line"):
        store.update_state("plan", {"phase": "no-write"}, kind="phase_changed", operation_id="op-partial")
    assert plan.events.read_bytes() == before + b'{"schema_version":1,"sequence":2'


def test_bad_checksum_or_state_cursor_blocks_read_and_mutation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)
    plan = store.plan_paths("plan")
    payload = json.loads(plan.events.read_text(encoding="utf-8"))
    payload["record_hash"] = "sha256:" + "0" * 64
    plan.events.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(IntegrityError):
        store.read_events("plan")
    before = plan.events.read_bytes()
    with pytest.raises(IntegrityError):
        store.update_state("plan", {"phase": "blocked"}, kind="phase_changed", operation_id="op-bad-hash")
    assert plan.events.read_bytes() == before

    # Restore trusted journal bytes, then make the snapshot cursor point past
    # that history.  Cursor linkage is checked independently of the semantic
    # digest, so this remains a blocking integrity error.
    store = _store(tmp_path / "cursor")
    _register(store)
    plan = store.plan_paths("plan")
    state = json.loads(plan.state.read_text(encoding="utf-8"))
    state["last_event_sequence"] = 9
    plan.state.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(IntegrityError, match="beyond"):
        store.read_state("plan")
    before = _business_snapshot(store, "plan")
    with pytest.raises(IntegrityError):
        store.update_state("plan", {"phase": "blocked"}, kind="phase_changed", operation_id="op-cursor")
    assert _business_snapshot(store, "plan") == before


@pytest.mark.parametrize("tamper", ["sequence", "previous_event_hash"])
def test_sequence_gap_and_hash_chain_mismatch_block_mutation(tmp_path: Path, tamper: str) -> None:
    store = _store(tmp_path)
    _register(store)
    store.update_state("plan", {"phase": "one"}, kind="phase_changed", operation_id="op-one")
    events_path = store.plan_paths("plan").events
    lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    if tamper == "sequence":
        lines[1]["sequence"] = 3
    else:
        lines[1]["previous_event_hash"] = "sha256:" + "1" * 64
    lines[1]["record_hash"] = ""
    lines[1]["record_hash"] = event_record_hash(validate_event(lines[1], expected_plan_id="plan", allow_unhashed=True))
    events_path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    before = _business_snapshot(store, "plan")
    with pytest.raises(IntegrityError):
        store.update_state("plan", {"phase": "blocked"}, kind="phase_changed", operation_id=f"op-{tamper}")
    assert _business_snapshot(store, "plan") == before


def test_future_journal_schema_blocks_without_quarantine(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)
    events = store.plan_paths("plan").events
    trusted = events.read_bytes()
    events.write_bytes(trusted + json.dumps({"schema_version": 99, "sequence": 2}).encode() + b"\n")
    with pytest.raises(FutureSchemaError):
        store.read_events("plan")
    assert not list(events.parent.glob("events.invalid.*"))


def test_limit_bands_and_over_limit_update_are_explicit(tmp_path: Path) -> None:
    assert state_size_band(STATE_TARGET_BYTES) == "target"
    assert state_size_band(STATE_TARGET_BYTES + 1) == "warning"
    assert state_size_band(STATE_WARNING_BYTES) == "warning"
    assert state_size_band(STATE_HARD_LIMIT_BYTES - 1) == "warning"
    assert state_size_band(STATE_HARD_LIMIT_BYTES) == "hard"
    assert state_size_band(STATE_HARD_LIMIT_BYTES + 1) == "hard"

    base = new_state("limit", now="2026-08-10T00:00:00+00:00")
    warning = validate_state(
        dict(base, semantic_hash="", open_blockers=["b" * 400 for _ in range(8)], open_questions=["q" * 400 for _ in range(8)])
    )
    assert encoded_size(warning) >= STATE_WARNING_BYTES
    assert validate_state(warning, hard_limit=encoded_size(warning))
    with pytest.raises(SchemaError):
        validate_state(warning, hard_limit=encoded_size(warning) - 1)

    store = _store(tmp_path)
    _register(store)
    plan = store.plan_paths("plan")
    current = store.read_state("plan")
    near_limit = validate_state(
        dict(
            current,
            semantic_hash="",
            open_blockers=["b" * 400 for _ in range(8)],
            open_questions=["q" * 400 for _ in range(8)],
        )
    )
    publish_json(plan.state, near_limit, hard_limit=STATE_HARD_LIMIT_BYTES)
    before = _business_snapshot(store, "plan")
    with pytest.raises(SchemaError):
        store.update_state(
            "plan",
            {"objective": "o" * 480, "active_files": [f"src/{index}-" + "x" * 300 for index in range(8)]},
            kind="validation_changed",
            operation_id="op-over-limit",
        )
    assert _business_snapshot(store, "plan") == before


def test_reader_writer_race_never_accepts_a_cursor_ahead_of_verified_history(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _register(store)
    started = threading.Event()
    release = threading.Event()
    import shared.implementation_store.store as store_module

    original_append = store_module.append_jsonl

    def blocked_append(path: Path, payload, **kwargs):
        result = original_append(path, payload, **kwargs)
        if path == store.plan_paths("plan").events:
            started.set()
            release.wait(timeout=5)
        return result

    errors: list[BaseException] = []
    store_module.append_jsonl = blocked_append

    def writer() -> None:
        try:
            store.update_state("plan", {"phase": "raced"}, kind="phase_changed", operation_id="op-race-reader")
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    assert started.wait(timeout=5)
    for _ in range(20):
        state = store.read_state("plan")
        assert state["last_event_sequence"] <= len(store.read_events("plan"))
    release.set()
    thread.join(timeout=5)
    store_module.append_jsonl = original_append
    assert not errors
    assert store.read_state("plan")["phase"] == "raced"
