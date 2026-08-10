from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "plans"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from implementation_notes_lib import Roots, append_entry, category_anchor, entry_html, html_document  # noqa: E402
from legacy_migration import (  # noqa: E402
    MigrationError,
    apply_migration,
    build_inventory,
    inventory_payload,
    rebuild_legacy_views,
)
from shared.implementation_store import ImplementationStore, resolve_store_paths  # noqa: E402


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "Migration Fixture")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "fixture")
    return root.resolve()


def _plan(root: Path, relative: str, *, approved: bool = True) -> Path:
    path = root / ".ralph" / "plans" / f"{relative}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    approval = "approved" if approved else "pending"
    path.write_text(
        f"# {Path(relative).name.title()}\n\n"
        "Implementation notes required: yes\n"
        f"Plan approval status: {approval}\n",
        encoding="utf-8",
    )
    return path


def _notes(root: Path, plan: Path, *, active_root: Path | None = None, operations: tuple[tuple[str, str, str], ...] = ()) -> Path:
    active = (active_root or root).resolve()
    relative = plan.relative_to(root / ".ralph" / "plans")
    notes = active / ".ralph" / "plans" / f"{relative.with_suffix('')}-implementation-notes.html"
    notes.parent.mkdir(parents=True, exist_ok=True)
    roots = Roots(active, root.resolve(), None, "fixture")
    notes.write_text(
        html_document(
            title=relative.stem,
            plan_path=root / ".ralph" / "plans" / relative,
            notes_path=notes,
            roots=roots,
            git_sha="0123456789abcdef",
            git_branch="fixture-branch",
            session_id="fixture-session",
            timestamp="2026-01-01T00:00:00+00:00",
        ),
        encoding="utf-8",
    )
    for operation, category, status in operations:
        append_entry(
            notes,
            entry_html(
                category=category,
                decision=f"Decision {operation}",
                reason=f"Reason {operation}",
                impact=f"Impact {operation}",
                related_files=["src/fixture.py"],
                status=status,
                timestamp=f"2026-01-01T0{len(operation)}:00:00+00:00" if len(operation) < 10 else "2026-01-01T01:00:00+00:00",
                operation_id=operation,
            ),
            category,
        )
    return notes


def _source_snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    plans = root / ".ralph" / "plans"
    result: dict[str, tuple[bytes, int]] = {}
    if not plans.exists():
        return result
    for path in sorted(plans.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name.endswith(".md") or path.name.endswith(".html") or path.name.endswith(".json"):
            result[str(path)] = (path.read_bytes(), path.stat().st_mtime_ns)
    return result


def _context(root: Path, *, active_root: Path | None = None):
    paths = resolve_store_paths(active_root=active_root or root, primary_root=root)
    return paths, build_inventory(paths, active_root=active_root or root)


def test_fixture_import_nested_preserves_material_fields_and_is_idempotent(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(root, "nested/demo")
    notes = _notes(
        root,
        plan,
        operations=(
            ("op-decision", "decision", "completed"),
            ("op-validation", "validation", "completed"),
        ),
    )
    (root / ".ralph" / "plans" / "implementation-index.json").write_text(
        json.dumps({"version": 2, "plans": [], "events": [], "loose_commits": []}) + "\n",
        encoding="utf-8",
    )
    (root / ".ralph" / "plans" / "implementation-index.md").write_text("# Index\n", encoding="utf-8")
    (root / ".ralph" / "plans" / "implementation-notes-consolidated.md").write_text("# View\n", encoding="utf-8")
    (root / ".ralph" / "plans" / "implementation-notes-consolidated.html").write_text("<main></main>\n", encoding="utf-8")
    before = _source_snapshot(root)

    paths, context = _context(root)
    report = inventory_payload(context)
    assert report["approved_plans"] == ["nested/demo"]
    assert report["expected_new_plan_ids"] == ["nested/demo"]
    assert report["expected_event_counts"] == {"nested/demo": 3}
    assert report["expected_state_reductions"][0]["expected_state_bytes"] > 0
    assert report["expected_state_reductions"][0]["state_reduction_bytes"] > 0
    assert report["notes_html"][0]["relative"] == "nested/demo-implementation-notes.html"
    assert report["index_markdown"]
    assert report["consolidated_views"]
    assert report["blocked"] is False

    applied = apply_migration(context)
    assert applied["imported_plans"] == 1
    assert applied["imported_events"] == 3
    verification = applied["verification"][0]
    assert verification["operation_ids"][:3] == [
        verification["operation_ids"][0],
        "op-decision",
        "op-validation",
    ]
    assert verification["event_count"] == 3
    assert verification["latest_material"]["operation_id"] == "op-validation"
    assert verification["latest_material"]["category"] == "validation"
    assert verification["latest_material"]["reason"] == "Reason op-validation"
    assert verification["latest_material"]["impact"] == "Impact op-validation"
    assert verification["branch"] == "fixture-branch"
    assert verification["commit"] == "0123456789abcdef"
    assert verification["session_id"] == "fixture-session"
    assert verification["workspace_instance_id"].startswith("ws-")
    assert all(item.startswith("sha256:") for item in verification["record_hashes"])
    assert _source_snapshot(root) == before

    store = ImplementationStore(paths)
    events_before = store.paths.for_plan("nested/demo").events.read_bytes()
    state_before = store.paths.for_plan("nested/demo").state.read_bytes()
    rerun_context = build_inventory(paths, active_root=root)
    rerun = apply_migration(rerun_context)
    assert rerun["imported_plans"] == 0
    assert rerun["imported_events"] == 0
    assert store.paths.for_plan("nested/demo").events.read_bytes() == events_before
    assert store.paths.for_plan("nested/demo").state.read_bytes() == state_before
    assert _source_snapshot(root) == before


def test_worktree_only_notes_are_discovered_and_written_to_primary_store(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(root, "worktree/demo")
    worktree = tmp_path / "linked-worktree"
    _git(root, "worktree", "add", "-q", "-b", "fixture-linked", str(worktree))
    notes = _notes(root, plan, active_root=worktree, operations=(("op-worktree", "decision", "active"),))
    before = notes.read_bytes(), notes.stat().st_mtime_ns

    paths, context = _context(root, active_root=worktree)
    report = inventory_payload(context)
    assert report["blocked"] is False
    assert report["approved_plans"] == ["worktree/demo"]
    assert any(item["location"] == "worktree" for item in report["expected_state_reductions"][0]["plan_copies"]) is False
    assert any(str(notes) == item["path"] for item in report["notes_html"])

    applied = apply_migration(context)
    assert applied["imported_plans"] == 1
    assert paths.primary_root == root.resolve()
    assert paths.for_plan("worktree/demo").state.is_file()
    assert (notes.read_bytes(), notes.stat().st_mtime_ns) == before


def test_divergent_worktree_copies_block_without_mutating_sources(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(root, "conflict/demo")
    primary_notes = _notes(root, plan, operations=(("op-primary", "decision", "active"),))
    worktree = tmp_path / "linked-worktree"
    _git(root, "worktree", "add", "-q", "-b", "fixture-divergent", str(worktree))
    worktree_notes = _notes(root, plan, active_root=worktree, operations=(("op-worktree", "decision", "active"),))
    before = {str(primary_notes): primary_notes.read_bytes(), str(worktree_notes): worktree_notes.read_bytes()}

    paths, context = _context(root, active_root=worktree)
    report = inventory_payload(context)
    assert report["blocked"] is True
    assert any(item["code"] == "divergent_notes_copies" for item in report["conflicts"])
    with pytest.raises(MigrationError, match="blocked") as error:
        apply_migration(context)
    assert error.value.code == "migration_blocked"
    assert primary_notes.read_bytes() == before[str(primary_notes)]
    assert worktree_notes.read_bytes() == before[str(worktree_notes)]
    assert not paths.root.exists()


def test_duplicate_operation_ids_block_before_any_new_store_write(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(root, "duplicate/demo")
    notes = _notes(root, plan, operations=(("op-duplicate", "decision", "active"),))
    duplicate = entry_html(
        category="decision",
        decision="A different payload with the same operation ID",
        reason="The importer must reject ambiguous identity.",
        impact="No canonical write is allowed.",
        related_files=["src/other.py"],
        status="active",
        timestamp="2026-01-01T10:00:00+00:00",
        operation_id="op-duplicate",
    )
    text = notes.read_text(encoding="utf-8")
    notes.write_text(text.replace(category_anchor("decision"), duplicate + category_anchor("decision"), 1), encoding="utf-8")
    before = _source_snapshot(root)

    paths, context = _context(root)
    report = inventory_payload(context)
    assert report["blocked"] is True
    assert any(item["code"] == "duplicate_operation_id" for item in report["conflicts"])
    with pytest.raises(MigrationError, match="blocked"):
        apply_migration(context)
    assert not paths.root.exists()
    assert _source_snapshot(root) == before


def test_index_events_merge_and_loose_commits_are_deduplicated(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(root, "indexed/demo")
    _notes(root, plan, operations=(("op-indexed", "decision", "completed"),))
    index_only = _plan(root, "indexed/index-only")
    timestamp = "2026-01-02T00:00:00+00:00"
    commit = "abcdef0123456789"
    index = {
        "version": 2,
        "canonical_repo_root": str(root),
        "plans": [
            {"plan": ".ralph/plans/indexed/demo.md", "status": "approved"},
            {"plan": ".ralph/plans/indexed/index-only.md", "status": "approved"},
        ],
        "events": [
            {
                "event": "note_appended",
                "plan": ".ralph/plans/indexed/demo.md",
                "status": "completed",
                "branch": "index-branch",
                "commit": commit,
                "session_id": "index-session",
                "workspace_instance_id": "index-workspace",
                "operation_id": "op-indexed",
                "timestamp": "2026-01-01T01:00:00+00:00",
                "summary": "Decision op-indexed",
            },
            {
                "event": "plan_updated",
                "plan": ".ralph/plans/indexed/index-only.md",
                "status": "active",
                "branch": "index-branch",
                "commit": commit,
                "session_id": "index-session",
                "workspace_instance_id": "index-workspace",
                "operation_id": "op-index-only",
                "timestamp": timestamp,
                "summary": "Index-only update",
            },
            {
                "event": "loose_commit_recorded",
                "commit": commit,
                "branch": "index-branch",
                "reason": "Loose commit",
                "notes_detail": "Loose detail",
                "created_at": timestamp,
                "timestamp": timestamp,
            },
        ],
        "loose_commits": [
            {
                "type": "loose_commit",
                "commit": commit,
                "branch": "index-branch",
                "reason": "Loose commit",
                "notes": "Loose detail",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ],
    }
    index_path = root / ".ralph" / "plans" / "implementation-index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    paths, context = _context(root)
    report = inventory_payload(context)
    assert report["index_source_totals"] == {"plans": 2, "events": 3, "loose_commits": 1}
    assert report["expected_event_counts"]["indexed/demo"] == 2
    assert report["expected_event_counts"]["indexed/index-only"] == 2
    assert report["loose_commit_count"] == 1
    assert report["blocked"] is False

    applied = apply_migration(context)
    store = ImplementationStore(paths)
    indexed_events = store.read_events("indexed/demo")
    index_only_events = store.read_events("indexed/index-only")
    assert [event["operation_id"] for event in indexed_events].count("op-indexed") == 1
    assert [event["operation_id"] for event in index_only_events][-1] == "op-index-only"
    assert len(store.read_unplanned_events()) == 1
    assert applied["loose_verification"][0]["operation_id"].startswith("mig-loose-")


def test_corrupt_future_checksum_and_alias_evidence_are_reported_as_blockers(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(root, "unsafe/demo")
    notes = _notes(root, plan)
    alias = root / ".ralph" / "plans" / "unsafe" / "alias-implementation-notes.html"
    alias.hardlink_to(notes)
    index_path = root / ".ralph" / "plans" / "implementation-index.json"
    index_path.write_text(
        json.dumps(
            {
                "version": 2,
                "plans": [],
                "events": [{"event": "plan_updated", "plan": ".ralph/plans/unsafe/demo.md", "event_id": "bad"}],
                "loose_commits": [],
            }
        ),
        encoding="utf-8",
    )
    paths, context = _context(root)
    report = inventory_payload(context)
    assert report["blocked"] is True
    assert report["aliases"]
    assert any(item["code"] == "bad_checksum" for item in report["conflicts"])
    assert not paths.root.exists()

    index_path.write_text("{not-json\n", encoding="utf-8")
    corrupt = inventory_payload(build_inventory(paths, active_root=root))
    assert corrupt["corrupt_schemas"]
    assert corrupt["blocked"] is True

    index_path.write_text(json.dumps({"version": 99, "plans": [], "events": [], "loose_commits": []}), encoding="utf-8")
    future = inventory_payload(build_inventory(paths, active_root=root))
    assert future["future_schemas"]
    assert future["blocked"] is True


def test_partial_apply_can_resume_and_rollback_export_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    plan = _plan(root, "resume/demo")
    _notes(root, plan, operations=(("op-resume", "decision", "completed"),))
    paths, context = _context(root)
    original = ImplementationStore.record_event
    interrupted = False

    def interrupt_once(self: ImplementationStore, *args, **kwargs):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise RuntimeError("fixture interruption")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ImplementationStore, "record_event", interrupt_once)
    with pytest.raises(RuntimeError, match="interruption"):
        apply_migration(context)
    monkeypatch.setattr(ImplementationStore, "record_event", original)
    resumed = apply_migration(build_inventory(paths, active_root=root))
    store = ImplementationStore(paths)
    assert resumed["imported_events"] == 1
    assert [event["operation_id"] for event in store.read_events("resume/demo")][1:] == ["op-resume"]

    journal_before = {
        str(path.relative_to(paths.root)): path.read_bytes()
        for path in paths.root.rglob("*")
        if path.is_file() and path.name != "migration.lock"
    }
    dry = rebuild_legacy_views(store, plan_id="resume/demo")
    assert dry["applied"] is False
    assert dry["output_digest"].startswith("sha256:")
    applied = rebuild_legacy_views(store, apply=True, plan_id="resume/demo")
    assert applied["applied"] is True
    assert applied["output_digest"] == dry["output_digest"]
    assert all((root / output).is_file() for output in applied["outputs"])
    round_trip_context = build_inventory(paths, active_root=root)
    assert round_trip_context.blocked is False
    assert apply_migration(round_trip_context)["imported_events"] == 0
    journal_after = {
        str(path.relative_to(paths.root)): path.read_bytes()
        for path in paths.root.rglob("*")
        if path.is_file() and path.name != "migration.lock"
    }
    assert journal_after == journal_before
    assert rebuild_legacy_views(store, plan_id="resume/demo")["output_digest"] == dry["output_digest"]
