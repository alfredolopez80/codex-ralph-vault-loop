from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
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
    RedContentError,
    SchemaError,
    StorePathError,
    ensure_store_layout,
    resolve_store_paths,
    state_semantic_hash,
    validate_event,
    validate_state,
)
from shared.implementation_store.io import CorruptRecordError  # noqa: E402
from shared.implementation_store.paths import STORE_RELATIVE  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return result


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "primary" / "project"
    root.mkdir(parents=True)
    git(root, "init")
    git(root, "config", "user.name", "Test User")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "initial")
    return root


def make_store(tmp_path: Path) -> tuple[Path, ImplementationStore]:
    primary = make_repo(tmp_path)
    paths = resolve_store_paths(primary_root=primary)
    return primary, ImplementationStore(paths)


def provenance() -> dict[str, object]:
    return {
        "git": {"branch": "main", "commit": "a" * 40, "workspace_instance_id": "ws-test"},
        "writer_session_id": "session-test",
        "model_family": "luna",
        "model_source": "payload",
        "model_verified": True,
    }


def test_empty_reads_are_side_effect_free(tmp_path: Path) -> None:
    primary, store = make_store(tmp_path)
    assert store.read_manifest() is None
    assert store.read_state("nested/plan") is None
    assert not (primary / STORE_RELATIVE).exists()


def test_layout_does_not_change_primary_checkout_permissions(tmp_path: Path) -> None:
    primary = make_repo(tmp_path)
    primary.chmod(0o755)
    paths = resolve_store_paths(primary_root=primary)

    ensure_store_layout(paths)

    assert stat.S_IMODE(primary.stat().st_mode) == 0o755
    assert stat.S_IMODE(paths.root.stat().st_mode) == 0o700


def test_resolver_targets_primary_from_linked_worktree(tmp_path: Path) -> None:
    primary = make_repo(tmp_path)
    linked = tmp_path / "linked" / "different-name"
    linked.parent.mkdir(parents=True)
    git(primary, "worktree", "add", "--detach", str(linked), "HEAD")
    paths = resolve_store_paths(active_root=linked)
    assert paths.primary_root == primary
    assert paths.root == primary / STORE_RELATIVE


def test_resolver_rejects_primary_from_different_repository(tmp_path: Path) -> None:
    primary = make_repo(tmp_path / "first")
    unrelated = make_repo(tmp_path / "second")
    with pytest.raises(StorePathError, match="different Git repository"):
        resolve_store_paths(active_root=primary, primary_root=unrelated)


def test_registration_creates_layout_and_manifest_pointer(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    result = store.register_plan("epic/phase-1", plan_path=".ralph/plans/epic.md", provenance=provenance(), now="2026-08-10T00:00:00+00:00")
    assert result.changed
    plan = store.plan_paths("epic/phase-1")
    assert plan.state.exists() and plan.events.exists() and plan.state_lock.exists()
    assert store.read_manifest()["plans"][0]["plan_id"] == "epic/phase-1"
    assert "events" not in store.read_manifest()
    assert stat.S_IMODE(plan.state.stat().st_mode) == 0o600
    assert stat.S_IMODE(plan.events.stat().st_mode) == 0o600
    assert stat.S_IMODE(plan.root.stat().st_mode) == 0o700


def test_manifest_changes_only_for_discovery_or_status_transition(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("plan", provenance=provenance(), now="2026-08-10T00:00:00+00:00")
    manifest = store.paths.manifest
    before = (manifest.read_bytes(), manifest.stat().st_mtime_ns)
    phase = store.update_state("plan", {"phase": "validation"}, kind="phase_changed", operation_id="op-phase", now="2026-08-10T00:01:00+00:00")
    assert phase.changed
    assert (manifest.read_bytes(), manifest.stat().st_mtime_ns) == before
    completed = store.record_event("plan", kind="completed", operation_id="op-complete", summary="done", now="2026-08-10T00:02:00+00:00")
    assert completed.changed
    assert manifest.read_bytes() != before[0]
    assert store.read_manifest()["plans"][0]["status"] == "completed"


def test_material_update_can_clear_phase_and_records_provenance(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("clear", phase="build", now="2026-08-10T00:00:00+00:00")
    result = store.update_state(
        "clear",
        {"phase": ""},
        kind="phase_changed",
        operation_id="op-clear",
        provenance={
            "git": {"branch": "feature", "commit": "b" * 40, "workspace_instance_id": "ws-2"},
            "model_family": "luna",
            "model_source": "payload",
            "model_verified": True,
        },
    )
    assert result.changed
    assert result.state["phase"] == ""
    assert result.state["model_family"] == "luna"
    assert result.state["git"]["branch"] == "feature"


def test_semantic_hash_excludes_observational_timestamps_and_session() -> None:
    base = validate_state({"schema_version": 1, "plan_id": "p", "updated_at": "one", "writer_session_id": "a"})
    changed = dict(base, updated_at="two", created_at="three", writer_session_id="b")
    assert state_semantic_hash(base) == state_semantic_hash(changed)


def test_state_hard_limit_rejected_before_layout_mutation(tmp_path: Path) -> None:
    primary, store = make_store(tmp_path)
    with pytest.raises(SchemaError):
        store.register_plan("too-large", objective="x" * 9_000)
    assert not (primary / STORE_RELATIVE).exists()


def test_event_validation_rejects_unknown_kind_and_bad_hash() -> None:
    with pytest.raises(SchemaError):
        validate_event({"schema_version": 1, "sequence": 1, "event_id": "evt-1", "operation_id": "op-1", "timestamp": "now", "kind": "tool_read"})
    with pytest.raises(SchemaError):
        validate_event(
            {
                "schema_version": 1,
                "sequence": 1,
                "event_id": "evt-1",
                "operation_id": "op-1",
                "timestamp": "now",
                "kind": "started",
                "record_hash": "sha256:" + "0" * 64,
            }
        )


def test_future_schema_is_hard_blocked_without_quarantine(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("future", now="2026-08-10T00:00:00+00:00")
    state = store.plan_paths("future").state
    payload = json.loads(state.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    state.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FutureSchemaError):
        store.read_state("future")
    assert state.exists()
    assert not list(state.parent.glob("state.invalid.*"))


def test_red_content_is_rejected_before_publication(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    with pytest.raises(RedContentError):
        store.register_plan("red", objective="pass" + "word" + "=" + "fixture-marker")
    assert not store.paths.root.exists()


def test_path_traversal_and_nested_validation(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    assert store.plan_paths("one/two").root.name == "two"
    for plan_id in ("../escape", "one/../escape", "/absolute", "one\\escape", "one//two"):
        with pytest.raises(StorePathError):
            store.plan_paths(plan_id)


def test_symlink_store_component_is_rejected(tmp_path: Path) -> None:
    primary = make_repo(tmp_path)
    (primary / ".local-notes").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    (tmp_path / "elsewhere").mkdir()
    with pytest.raises(StorePathError):
        resolve_store_paths(primary_root=primary)


def test_hardlinked_store_file_is_rejected(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("hardlink", now="2026-08-10T00:00:00+00:00")
    plan = store.plan_paths("hardlink")
    alias = plan.root / "alias.json"
    os.link(plan.state, alias)
    with pytest.raises((StorePathError, CorruptRecordError)):
        store.read_state("hardlink")


def test_concurrent_material_updates_keep_one_sequence_and_hash_chain(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("concurrent", now="2026-08-10T00:00:00+00:00")

    def update(index: int):
        return store.update_state(
            "concurrent",
            {"phase": f"phase-{index}"},
            kind="phase_changed",
            operation_id=f"op-concurrent-{index}",
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(update, range(6)))
    assert all(result.changed for result in results)
    events = store.read_events("concurrent")
    assert [event["sequence"] for event in events] == list(range(1, 8))
    assert all(event["record_hash"].startswith("sha256:") for event in events)


def test_hard_event_limit_is_rejected_without_journal_mutation(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("event-limit", now="2026-08-10T00:00:00+00:00")
    events = store.plan_paths("event-limit").events
    before = events.read_bytes()
    with pytest.raises(SchemaError):
        store.record_event("event-limit", kind="decision", operation_id="op-too-large", summary="x" * 1_000)
    assert events.read_bytes() == before


def test_same_operation_id_is_idempotent_and_different_payload_blocks(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("idem", now="2026-08-10T00:00:00+00:00")
    first = store.update_state("idem", {"phase": "build"}, kind="phase_changed", operation_id="op-same", now="2026-08-10T00:01:00+00:00")
    state = store.plan_paths("idem").state
    snapshot = (state.read_bytes(), state.stat().st_mtime_ns)
    retry = store.update_state("idem", {"phase": "build"}, kind="phase_changed", operation_id="op-same", now="2026-08-10T00:03:00+00:00")
    assert first.changed and not retry.changed
    assert (state.read_bytes(), state.stat().st_mtime_ns) == snapshot
    with pytest.raises(IdempotencyError):
        store.update_state("idem", {"phase": "different"}, kind="phase_changed", operation_id="op-same")
    assert len(store.read_events("idem")) == 2


def test_context_ledger_claim_is_content_free_and_read_only_on_hit(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("ledger", now="2026-08-10T00:00:00+00:00")
    record = {
        "schema_version": 1,
        "project_id": "project-test",
        "workspace_instance_id": "ws-test",
        "session_id": "session-test",
        "context_epoch": "startup-1",
        "plan_id": "ledger",
        "progress_generation": 1,
        "capsule_kind": "full",
        "emission_id": "ctx-deterministic-1",
    }
    first = store.claim_context_emission(record)
    assert first.emitted
    ledger = store.paths.context_ledger
    before = (ledger.read_bytes(), ledger.stat().st_mtime_ns)
    retry = store.claim_context_emission(record)
    assert not retry.emitted and retry.reason == "ledger hit"
    assert (ledger.read_bytes(), ledger.stat().st_mtime_ns) == before
    persisted = store.read_context_ledger()
    assert len(persisted) == 1
    assert set(persisted[0]) == set(record)


def test_hash_chain_and_unplanned_commit_are_bounded(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("chain", now="2026-08-10T00:00:00+00:00")
    store.record_event("chain", kind="decision", summary="Use snapshot", operation_id="op-decision", now="2026-08-10T00:01:00+00:00")
    events = store.read_events("chain")
    assert events[0]["previous_event_hash"] == ""
    assert events[1]["previous_event_hash"] == events[0]["record_hash"]
    loose = store.append_unplanned_commit(operation_id="op-loose", summary="Loose commit", references=["README.md"], now="2026-08-10T00:02:00+00:00")
    assert loose.changed and len(store.read_unplanned_events()) == 1


def test_atomic_publication_fsyncs_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _primary, store = make_store(tmp_path)
    calls: list[Path] = []
    import shared.implementation_store.io as io

    monkeypatch.setattr(io, "_fsync_directory", lambda path: calls.append(path))
    store.register_plan("fsync", now="2026-08-10T00:00:00+00:00")
    assert calls


def test_malformed_current_state_is_quarantined_only_at_write_boundary(tmp_path: Path) -> None:
    _primary, store = make_store(tmp_path)
    store.register_plan("broken", now="2026-08-10T00:00:00+00:00")
    state = store.plan_paths("broken").state
    state.write_text("{not-json", encoding="utf-8")
    with pytest.raises(CorruptRecordError):
        store.read_state("broken")
    with pytest.raises(Exception, match="not registered"):
        store.update_state("broken", {"phase": "repair"}, operation_id="op-repair")
    assert list(state.parent.glob("state.invalid.*"))
