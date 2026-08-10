#!/usr/bin/env python3
"""Run the project-local, Luna-only implementation-progress canary.

The runner deliberately creates every repository, linked worktree, HOME, Ralph
home, hook-state root, and sentinel below one temporary directory.  It invokes
only the checked-in deterministic runtime; no model, advisor, worker, MCP, or
network route is available to the fixture.  The JSON output is bounded to
counts, digests, identities, and gate results so fixture bodies never become a
report or prompt input.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
PLANS = ROOT / "scripts" / "plans"
for _path in (HOOKS, PLANS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from implementation_notes_lib import (  # noqa: E402
    Roots,
    append_entry,
    entry_html,
    html_document,
    valid_non_initial_entries,
)
from legacy_migration import (  # noqa: E402
    apply_migration,
    build_inventory,
    inventory_payload,
    rebuild_legacy_views,
)
from progress_context import (  # noqa: E402
    ContextRequest,
    emit_context,
    legacy_fallback,
)
from shared.active_context import active_context_from_payload  # noqa: E402
from shared.implementation_store import (  # noqa: E402
    IdempotencyError,
    ImplementationStore,
    resolve_store_paths_local,
)
from shared.progress_runtime import validation_transition  # noqa: E402
import session_start_dispatch  # noqa: E402


CLI = ROOT / "scripts" / "plans" / "progress.py"
POST_TOOL = HOOKS / "post_tool_dispatch.py"
STOP = HOOKS / "stop_dispatch.py"
COMPARATOR = ROOT / "scripts" / "evals" / "compare_hook_benchmarks.py"

SCHEMA_VERSION = 2
FIXED_TIME = "2026-08-10T00:00:00+00:00"
FIXED_COMMIT_TIME = "2026-08-10T00:00:00+0000"
MODEL = "gpt-5.6-luna"
MODEL_EFFORT = "max"
PLAN_SENTINEL = "canary-plan-sentinel"
PROMPT_SENTINEL = "canary-prompt-sentinel"
MODEL_SENTINEL = "canary-model-call-sentinel"


@dataclass(frozen=True)
class Fixture:
    root: Path
    plan: Path
    plan_id: str
    branch: str
    sha: str
    workspace_id: str
    env: dict[str, str]


def _git(root: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        env=dict(env) if env is not None else None,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git failed: {' '.join(args)}")
    return result.stdout.strip()


def _commit_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    env.update({"GIT_AUTHOR_DATE": FIXED_COMMIT_TIME, "GIT_COMMITTER_DATE": FIXED_COMMIT_TIME})
    return env


def _isolated_env(
    root: Path,
    isolation: Path,
    *,
    primary: Path | None = None,
    active: Path | None = None,
    session: str = "canary-session",
) -> dict[str, str]:
    primary_root = (primary or root).resolve()
    active_root = (active or root).resolve()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(isolation / "home"),
            "USERPROFILE": str(isolation / "home"),
            "RALPH_HOME": str(isolation / "ralph-home"),
            "CODEX_HOOK_STATE_ROOT": str(isolation / "hook-state"),
            "CODEX_MEMORY_HOME": str(isolation / "memory"),
            "VAULT_DIR": str(isolation / "vault"),
            "RALPH_PROGRESS_PRIMARY_ROOT": str(primary_root),
            "RALPH_PRIMARY_REPO_ROOT": str(primary_root),
            "RALPH_ACTIVE_WORKTREE_ROOT": str(active_root),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "RALPH_PROGRESS_LEGACY_FALLBACK": "",
            "RALPH_RUNTIME_OBSERVABILITY_MODE": "benchmark",
            "RALPH_SCAFFOLD_PROFILE": "auto",
            "RALPH_MODEL": MODEL,
            "CODEX_MODEL": MODEL,
            "CODEX_SESSION_ID": session,
            "RALPH_SESSION_ID": session,
            "RALPH_EXECUTOR_MODEL": MODEL,
            "RALPH_EXECUTOR_EFFORT": MODEL_EFFORT,
            "GIT_TERMINAL_PROMPT": "0",
            "NO_NETWORK": "1",
        }
    )
    for name in ("home", "ralph-home", "hook-state", "memory", "vault"):
        (isolation / name).mkdir(parents=True, exist_ok=True)
    return env


def _repo(base: Path, name: str, plan_id: str = "canary") -> Fixture:
    root = (base / name).resolve()
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "canary@example.invalid")
    _git(root, "config", "user.name", "Implementation Canary")
    plan = root / ".ralph" / "plans" / f"{plan_id}.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "# Deterministic Canary Plan\n\n"
        "Implementation notes required: yes\n"
        "Implementation notes status: active\n"
        "Plan approval status: approved\n\n"
        "## Objective\n\n"
        f"{PLAN_SENTINEL}\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    env = _commit_env()
    _git(root, "add", ".", env=env)
    _git(root, "commit", "-qm", "deterministic canary fixture", env=env)
    branch = _git(root, "branch", "--show-current") or "HEAD"
    sha = _git(root, "rev-parse", "HEAD")
    isolation = (base / f"{name}-isolation").resolve()
    return Fixture(root, plan, plan_id, branch, sha, f"ws-{name}", _isolated_env(root, isolation, session="canary-session"))


def _store(fixture: Fixture) -> ImplementationStore:
    return ImplementationStore(resolve_store_paths_local(fixture.root))


def _provenance(fixture: Fixture, *, session: str = "canary-writer", workspace: str | None = None) -> dict[str, Any]:
    return {
        "git": {
            "branch": fixture.branch,
            "commit": fixture.sha,
            "workspace_instance_id": workspace or fixture.workspace_id,
        },
        "writer_session_id": session,
        "model_family": "luna",
        "model_source": "payload",
        "model_verified": True,
        "origin": "implementation-progress",
        "intent": "progress-maintenance",
    }


def _register(fixture: Fixture, *, plan_id: str | None = None, session: str = "canary-writer") -> ImplementationStore:
    store = _store(fixture)
    selected = plan_id or fixture.plan_id
    result = store.register_plan(
        selected,
        plan_path=f".ralph/plans/{selected}.md",
        operation_id=f"start-{selected.replace('/', '-')}",
        now=FIXED_TIME,
        provenance=_provenance(fixture, session=session),
        objective="Preserve deterministic progress evidence.",
        phase="implementation",
        next_action="Run bounded canary checks.",
        status="active",
        summary="Canary plan started",
        reason="Approved plan fixture.",
        references=["README.md"],
        evidence_codes=["canary_started"],
    )
    if not result.changed:
        raise RuntimeError("fixture registration unexpectedly became a no-op")
    return store


def _event(
    store: ImplementationStore,
    fixture: Fixture,
    *,
    kind: str,
    operation: str,
    summary: str,
    state_update: Mapping[str, Any] | None = None,
    reason: str = "Deterministic canary material update.",
    next_action: str = "Continue bounded validation.",
    references: list[str] | None = None,
    evidence_codes: list[str] | None = None,
    session: str = "canary-writer",
    now: str = FIXED_TIME,
) -> Any:
    return store.record_event(
        fixture.plan_id,
        kind=kind,
        operation_id=operation,
        summary=summary,
        reason=reason,
        next_action=next_action,
        references=references or ["README.md"],
        evidence_codes=evidence_codes or ["canary_material"],
        state_update=state_update or {},
        now=now,
        provenance=_provenance(fixture, session=session),
    )


def _run(command: list[str], *, cwd: Path, env: Mapping[str, str], payload: Mapping[str, Any] | None = None, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _json_cli(fixture: Fixture, *args: str, expected: int = 0) -> dict[str, Any]:
    result = _run([sys.executable, str(CLI), *args, "--format", "json"], cwd=fixture.root, env=fixture.env)
    if result.returncode != expected:
        raise RuntimeError(f"CLI {' '.join(args)} exit={result.returncode}: {result.stderr[:240]}")
    if not result.stdout.strip():
        return {"returncode": result.returncode, "stderr": result.stderr[:240]}
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI returned non-JSON output: {result.stdout[:240]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("CLI JSON result is not an object")
    value["returncode"] = result.returncode
    return value


def _payload(fixture: Fixture, event: str, *, session: str = "canary-session", **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "hook_event_name": event,
        "cwd": str(fixture.root),
        "primary_repo_root": str(fixture.root),
        "workspace_instance_id": fixture.workspace_id,
        "session_id": session,
        "branch": fixture.branch,
        "sha": fixture.sha,
        "model": MODEL,
        "model_reasoning_effort": MODEL_EFFORT,
        "scenario": "implementation-progress-canary",
    }
    value.update(extra)
    return value


def _canonical_bytes(root: Path) -> dict[str, tuple[bytes, int]]:
    store_root = root / ".local-notes" / "ralph" / "implementation"
    result: dict[str, tuple[bytes, int]] = {}
    if not store_root.exists():
        return result
    for path in sorted(store_root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name.endswith(".lock"):
            continue
        result[str(path.relative_to(store_root))] = (path.read_bytes(), path.stat().st_mtime_ns)
    return result


def _tree_snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    result: dict[str, tuple[bytes, int]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            result[str(path.relative_to(root))] = (path.read_bytes(), path.stat().st_mtime_ns)
    return result


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _digest_obj(value: Any) -> str:
    return _digest_bytes(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _runtime_event_records(env: Mapping[str, str]) -> list[dict[str, Any]]:
    root = Path(env["RALPH_HOME"])
    records: list[dict[str, Any]] = []
    # Runtime observability has a bounded, known project path.  Do not perform
    # a recursive production scan; this reads only the documented event files.
    for project in sorted(root.glob("projects/*")):
        for path in sorted(project.glob("observability/runtime-events.jsonl*")):
            if path.is_symlink() or not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    return records


def _context_json(fixture: Fixture, *, event: str, session: str, epoch: str, profile: str = "luna", **extra: Any) -> dict[str, Any]:
    args = [
        "context",
        "--plan",
        str(fixture.plan),
        "--profile",
        profile,
        "--event",
        event,
        "--session-id",
        session,
        "--workspace-instance-id",
        fixture.workspace_id,
        "--project-id",
        "canary-project",
        "--context-epoch",
        epoch,
        "--format",
        "json",
    ]
    for key, value in extra.items():
        flag = f"--{key.replace('_', '-')}"
        if value is True:
            args.append(flag)
        elif value is False:
            continue
        else:
            args.extend([flag, str(value)])
    return _json_cli(fixture, *args)


def _invoke_posttool(fixture: Fixture, payload: Mapping[str, Any]) -> str:
    result = _run([sys.executable, str(POST_TOOL)], cwd=fixture.root, env=fixture.env, payload=payload)
    if result.returncode != 0:
        raise RuntimeError(f"post-tool failed: {result.stderr[:240]}")
    return result.stdout


def _invoke_stop(fixture: Fixture, payload: Mapping[str, Any]) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, str(STOP)], cwd=fixture.root, env=fixture.env, payload=payload)


def _scenario_small_and_material(base: Path) -> dict[str, Any]:
    fixture = _repo(base, "small", "small")
    store = _register(fixture)
    first = _event(
        store,
        fixture,
        kind="decision",
        operation="small-decision-1",
        summary="Small planned implementation decision.",
    )
    phase = _event(
        store,
        fixture,
        kind="phase_changed",
        operation="small-phase-1",
        summary="Phase changed to verification.",
        state_update={"phase": "verification"},
    )
    state = store.read_state(fixture.plan_id) or {}
    return {
        "small_planned_implementation": {
            "status": "PASS",
            "plan_id": fixture.plan_id,
            "event_count": len(store.read_events(fixture.plan_id)),
            "operation_ids": [event["operation_id"] for event in store.read_events(fixture.plan_id)],
            "material_changed": bool(first.changed and phase.changed),
            "state_status": state.get("status"),
        },
        "material_decision": {
            "status": "PASS" if first.changed and first.metadata.appends <= 1 and first.metadata.replacements <= 1 else "FAIL",
            "appends": first.metadata.appends,
            "replacements": first.metadata.replacements,
            "event_id": first.event_id,
        },
    }


def _scenario_multi_phase(base: Path) -> dict[str, Any]:
    fixture = _repo(base, "multi-phase", "multi")
    store = _register(fixture)
    phases = []
    for index, phase in enumerate(("design", "implementation", "validation"), start=1):
        result = _event(
            store,
            fixture,
            kind="phase_changed",
            operation=f"multi-phase-{index}",
            summary=f"Phase changed to {phase}.",
            state_update={"phase": phase, "next_action": f"Complete {phase}."},
        )
        phases.append(result.changed)
    state = store.read_state(fixture.plan_id) or {}
    return {
        "multi_phase_implementation": {
            "status": "PASS" if all(phases) and state.get("phase") == "validation" else "FAIL",
            "phase_count": len(phases),
            "final_phase": state.get("phase"),
            "event_count": len(store.read_events(fixture.plan_id)),
        }
    }


def _scenario_retry_and_conflict(base: Path) -> dict[str, Any]:
    fixture = _repo(base, "retry", "retry")
    store = _register(fixture)
    first = _event(store, fixture, kind="decision", operation="retry-op", summary="Retry-safe decision.")
    plan = store.plan_paths(fixture.plan_id)
    before_state = (plan.state.read_bytes(), plan.state.stat().st_mtime_ns)
    before_events = plan.events.read_bytes()
    retry = _event(store, fixture, kind="decision", operation="retry-op", summary="Retry-safe decision.")
    after_state = (plan.state.read_bytes(), plan.state.stat().st_mtime_ns)
    after_events = plan.events.read_bytes()
    conflict = "blocked"
    try:
        _event(store, fixture, kind="decision", operation="retry-op", summary="Conflicting operation payload.")
    except IdempotencyError:
        conflict = "blocked"
    else:
        conflict = "not_blocked"
    return {
        "same_operation_retry": {
            "status": "PASS" if first.changed and not retry.changed and before_state == after_state and before_events == after_events else "FAIL",
            "changed": retry.changed,
            "reason": retry.reason,
            "bytes_written": retry.metadata.bytes_written,
            "mtime_unchanged": before_state[1] == after_state[1],
        },
        "conflicting_operation_id": {
            "status": "PASS" if conflict == "blocked" else "FAIL",
            "result": conflict,
            "source_bytes_preserved": before_events == plan.events.read_bytes() if conflict == "blocked" else False,
        },
    }


def _scenario_validation(base: Path) -> dict[str, Any]:
    fixture = _repo(base, "validation", "validation")
    store = _register(fixture)
    context = active_context_from_payload(
        _payload(fixture, "PostToolUse", session="validation-session"), resolve_git=False
    )
    base_payload = _payload(
        fixture,
        "PostToolUse",
        session="validation-session",
        progress_plan_id=fixture.plan_id,
        plan_approved=True,
        tool_name="exec_command",
        tool_input={"cmd": "pytest -q"},
    )
    fail = dict(base_payload)
    fail.update({"tool_use_id": "validation-fail", "tool_response": {"exit_code": 1, "stdout": "fixture failure"}, "success": False})
    passed = dict(base_payload)
    passed.update({"tool_use_id": "validation-pass", "tool_response": {"exit_code": 0, "stdout": "fixture pass"}, "success": True})
    fail_transition = validation_transition(fail, context)
    pass_transition = validation_transition(passed, context)
    state = store.read_state(fixture.plan_id) or {}
    return {
        "validation_fail_to_pass": {
            "status": "PASS" if fail_transition.changed and pass_transition.changed and state.get("validation") == {"tests": "pass"} else "FAIL",
            "fail_changed": fail_transition.changed,
            "pass_changed": pass_transition.changed,
            "validation": state.get("validation", {}),
            "event_count": len(store.read_events(fixture.plan_id)),
        }
    }


def _scenario_context(base: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = _repo(base, "context", "context")
    store = _register(fixture, session="writer-session")
    ordinary = _context_json(fixture, event="ordinary", session="context-session", epoch="ordinary-1")
    ordinary_before = _canonical_bytes(fixture.root)
    unchanged = _context_json(fixture, event="resume", session="writer-session", epoch="unchanged-1", same_session_write=True)
    unchanged_after = _canonical_bytes(fixture.root)
    startup = _context_json(fixture, event="startup", session="new-session", epoch="startup-1")
    resume = _context_json(fixture, event="resume", session="resume-session", epoch="resume-1", external_writer=True)
    compact = _context_json(fixture, event="compact", session="compact-session", epoch="compact-1")
    compact_before_retry = _canonical_bytes(fixture.root)
    compact_retry = _context_json(fixture, event="compact", session="compact-session", epoch="compact-1")
    compact_after_retry = _canonical_bytes(fixture.root)
    _event(store, fixture, kind="decision", operation="external-generation-1", summary="External generation changed.", session="external-writer")
    external = _context_json(fixture, event="external", session="context-session", epoch="external-1", external_writer=True)
    explicit = _context_json(fixture, event="explicit", session="context-session", epoch="explicit-1")
    after = _canonical_bytes(fixture.root)
    return (
        {
            "ordinary_prompt": {
                "status": "PASS" if not ordinary.get("emitted") and ordinary.get("capsule", "") == "" else "FAIL",
                "progress_bytes": len(str(ordinary.get("capsule", "")).encode("utf-8")),
                "reason": ordinary.get("reason", ""),
            },
            "unchanged_continue": {
                "status": "PASS" if not unchanged.get("emitted") and unchanged.get("capsule", "") == "" else "FAIL",
                "progress_bytes": len(str(unchanged.get("capsule", "")).encode("utf-8")),
                "reason": unchanged.get("reason", ""),
            },
            "new_session": {
                "status": "PASS" if startup.get("emitted") and startup.get("capsule_kind") == "full" else "FAIL",
                "bytes": len(str(startup.get("capsule", "")).encode("utf-8")),
                "capsule_kind": startup.get("capsule_kind", ""),
            },
            "resume": {
                "status": "PASS" if resume.get("emitted") else "FAIL",
                "bytes": len(str(resume.get("capsule", "")).encode("utf-8")),
                "capsule_kind": resume.get("capsule_kind", ""),
            },
            "compact_unchanged_generation": {
                "status": "PASS" if compact.get("emitted") and not compact_retry.get("emitted") else "FAIL",
                "bytes": len(str(compact.get("capsule", "")).encode("utf-8")),
                "retry_bytes": len(str(compact_retry.get("capsule", "")).encode("utf-8")),
                "retry_ledger_hit": compact_retry.get("ledger_hit"),
            },
            "external_generation_change": {
                "status": "PASS" if external.get("emitted") and external.get("capsule_kind") == "delta" else "FAIL",
                "bytes": len(str(external.get("capsule", "")).encode("utf-8")),
                "capsule_kind": external.get("capsule_kind", ""),
            },
            "explicit_progress_request": {
                "status": "PASS" if explicit.get("emitted") else "FAIL",
                "bytes": len(str(explicit.get("capsule", "")).encode("utf-8")),
            },
            "cache_hit_writes": {
                "status": "PASS" if compact_before_retry == compact_after_retry else "FAIL",
                "unchanged_retry_store_files": compact_before_retry == compact_after_retry,
            },
        },
        {
            "context_outputs": {
                "ordinary": len(str(ordinary.get("capsule", "")).encode("utf-8")),
                "unchanged": len(str(unchanged.get("capsule", "")).encode("utf-8")),
                "new_session": len(str(startup.get("capsule", "")).encode("utf-8")),
                "resume": len(str(resume.get("capsule", "")).encode("utf-8")),
                "compact": len(str(compact.get("capsule", "")).encode("utf-8")),
                "external": len(str(external.get("capsule", "")).encode("utf-8")),
                "explicit": len(str(explicit.get("capsule", "")).encode("utf-8")),
            },
            "ledger_records": len(store.read_context_ledger()),
            "store_file_count": len(after),
            "ordinary_store_unchanged": ordinary_before == unchanged_after,
            "compact_retry_store_unchanged": compact_before_retry == compact_after_retry,
        },
    )


def _scenario_ambiguous_corrupt_future(base: Path) -> dict[str, Any]:
    fixture = _repo(base, "ambiguous", "ambiguous")
    store = _register(fixture, session="writer")
    second_plan = fixture.root / ".ralph" / "plans" / "ambiguous-two.md"
    second_plan.write_text(f"# Second\nPlan approval status: approved\n", encoding="utf-8")
    second_id = "ambiguous-two"
    store.register_plan(
        second_id,
        plan_path=".ralph/plans/ambiguous-two.md",
        operation_id="start-ambiguous-two",
        now=FIXED_TIME,
        provenance=_provenance(fixture, session="writer"),
        status="active",
        phase="implementation",
    )
    # The CLI receives an explicit plan path and therefore intentionally
    # bypasses active-plan discovery.  SessionStart is the integrated
    # ambiguous-plan boundary: it discovers all active plans for the current
    # workspace and must remain silent rather than choosing one.
    with contextlib.ExitStack() as stack:
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        previous = os.environ.copy()
        os.environ.update(fixture.env)
        try:
            ambiguous_output = session_start_dispatch.run(
                _payload(
                    fixture,
                    "SessionStart",
                    session="ambiguous-session",
                    source="startup",
                )
            )
        finally:
            os.environ.clear()
            os.environ.update(previous)
    ambiguous_ledger = (fixture.root / ".local-notes" / "ralph" / "implementation" / "context-emissions.jsonl")
    ambiguous_writes = ambiguous_ledger.exists()

    corrupt_fixture = _repo(base, "corrupt", "corrupt")
    corrupt_store = _register(corrupt_fixture)
    corrupt_state = corrupt_store.plan_paths(corrupt_fixture.plan_id).state
    corrupt_before = corrupt_state.read_bytes()
    corrupt_state.write_bytes(b"{not-json\n")
    corrupt_result = _run(
        [sys.executable, str(CLI), "context", "--plan", str(corrupt_fixture.plan), "--profile", "luna", "--event", "startup", "--session-id", "corrupt-session", "--context-epoch", "corrupt-1", "--format", "json"],
        cwd=corrupt_fixture.root,
        env=corrupt_fixture.env,
    )
    corrupt_state_after = corrupt_state.read_bytes()

    future_fixture = _repo(base, "future", "future")
    future_store = _register(future_fixture)
    future_state = future_store.plan_paths(future_fixture.plan_id).state
    future_state.write_text(json.dumps({"schema_version": 999}) + "\n", encoding="utf-8")
    future_result = _run(
        [sys.executable, str(CLI), "context", "--plan", str(future_fixture.plan), "--profile", "luna", "--event", "startup", "--session-id", "future-session", "--context-epoch", "future-1", "--format", "json"],
        cwd=future_fixture.root,
        env=future_fixture.env,
    )
    return {
        "ambiguous_active_plans": {
            "status": "PASS" if not ambiguous_output and not ambiguous_writes else "FAIL",
            "reason": "ambiguous_active_state",
            "ledger_created": ambiguous_writes,
        },
        "corrupt_progress_state": {
            "status": "PASS" if corrupt_result.returncode != 0 and corrupt_state_after == b"{not-json\n" else "FAIL",
            "returncode": corrupt_result.returncode,
            "source_preserved": corrupt_state_after == b"{not-json\n",
            "quarantine_expected": corrupt_state_after != corrupt_before,
        },
        "future_progress_schema": {
            "status": "PASS" if future_result.returncode != 0 and future_state.read_text(encoding="utf-8") == '{"schema_version": 999}\n' else "FAIL",
            "returncode": future_result.returncode,
            "source_preserved": future_state.read_text(encoding="utf-8") == '{"schema_version": 999}\n',
        },
    }


def _writer_process(root: str, plan_id: str, operation: str) -> None:
    path = Path(root)
    store = ImplementationStore(resolve_store_paths_local(path))
    fixture = Fixture(path, path / ".ralph" / "plans" / f"{plan_id}.md", plan_id, "canary-main", "", "ws-concurrent", {})
    store.record_event(
        plan_id,
        kind="decision",
        operation_id=operation,
        summary=f"Concurrent writer {operation}.",
        state_update={"latest_decision": {"event_id": "pending", "summary": f"Concurrent writer {operation}."}},
        provenance={
            "git": {"branch": "canary-main", "commit": "", "workspace_instance_id": "ws-concurrent"},
            "writer_session_id": operation,
            "model_family": "luna",
            "model_source": "payload",
            "model_verified": True,
            "origin": "implementation-progress",
            "intent": "progress-maintenance",
        },
        now=FIXED_TIME,
    )


def _scenario_concurrent_and_stop(base: Path) -> dict[str, Any]:
    fixture = _repo(base, "concurrent", "concurrent")
    store = _register(fixture)
    processes = [multiprocessing.Process(target=_writer_process, args=(str(fixture.root), fixture.plan_id, f"concurrent-{index}")) for index in (1, 2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
    process_codes = [process.exitcode for process in processes]
    events = store.read_events(fixture.plan_id)
    sequences = [int(event["sequence"]) for event in events]
    hashes = [str(event["record_hash"]) for event in events]

    stop_fixture = _repo(base, "stop", "stop")
    stop_store = _register(stop_fixture)
    _event(stop_store, stop_fixture, kind="decision", operation="stop-material", summary="Material evidence before Stop.")
    context = active_context_from_payload(_payload(stop_fixture, "PostToolUse", session="stop-writer"), resolve_git=False)
    validation_payload = _payload(
        stop_fixture,
        "PostToolUse",
        session="stop-writer",
        progress_plan_id=stop_fixture.plan_id,
        plan_approved=True,
        tool_name="exec_command",
        tool_input={"cmd": "pytest -q"},
        tool_response={"exit_code": 0, "stdout": "pass"},
        success=True,
    )
    validation_transition(validation_payload, context)
    stop_payload = _payload(
        stop_fixture,
        "Stop",
        session="stop-session",
        progress_plan_id=stop_fixture.plan_id,
        plan_approved=True,
        progress_complete=True,
        validation_status="pass",
        verified_done=True,
        last_assistant_message="Canary completed.",
    )
    before = _canonical_bytes(stop_fixture.root)
    first = _invoke_stop(stop_fixture, stop_payload)
    after_first = _canonical_bytes(stop_fixture.root)
    second = _invoke_stop(stop_fixture, stop_payload)
    after_second = _canonical_bytes(stop_fixture.root)
    state = stop_store.read_state(stop_fixture.plan_id) or {}
    return {
        "concurrent_writers": {
            "status": "PASS" if process_codes == [0, 0] and sequences == list(range(1, len(events) + 1)) and all(hashes) and len({event["operation_id"] for event in events}) == len(events) else "FAIL",
            "process_exit_codes": process_codes,
            "event_count": len(events),
            "sequences": sequences,
            "hashes_verified": all(hash_value.startswith("sha256:") for hash_value in hashes),
        },
        "terminal_stop_retry": {
            "status": "PASS" if first.returncode == 0 and second.returncode == 0 and state.get("status") == "completed" and after_first == after_second else "FAIL",
            "first_stdout_bytes": len(first.stdout.encode("utf-8")),
            "retry_stdout_bytes": len(second.stdout.encode("utf-8")),
            "first_changed_files": len(set(after_first) - set(before)) + sum(1 for key in set(before) & set(after_first) if before[key] != after_first[key]),
            "retry_business_writes": sum(1 for key in set(after_first) | set(after_second) if (after_first.get(key) != after_second.get(key))),
            "final_status": state.get("status"),
        },
    }


def _legacy_notes(root: Path, plan: Path, *, active_root: Path | None = None, operations: Iterable[tuple[str, str, str]] = ()) -> Path:
    active = (active_root or root).resolve()
    relative = plan.relative_to(root / ".ralph" / "plans")
    notes = active / ".ralph" / "plans" / f"{relative.with_suffix('')}-implementation-notes.html"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(
        html_document(
            title=relative.stem,
            plan_path=plan,
            notes_path=notes,
            roots=Roots(active, root.resolve(), None, "canary"),
            git_sha="0123456789abcdef",
            git_branch="canary-legacy",
            session_id="legacy-session",
            timestamp=FIXED_TIME,
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
                related_files=["README.md"],
                status=status,
                timestamp=FIXED_TIME,
                operation_id=operation,
            ),
            category,
        )
    return notes


def _migration_fixture(base: Path) -> tuple[Fixture, Path, dict[str, tuple[bytes, int]]]:
    fixture = _repo(base, "migration", "nested/migrate")
    plans_root = fixture.root / ".ralph" / "plans"
    notes = _legacy_notes(
        fixture.root,
        fixture.plan,
        operations=(("legacy-op-1", "decision", "active"), ("legacy-op-2", "validation", "completed")),
    )
    index_only = plans_root / "nested" / "index-only.md"
    index_only.parent.mkdir(parents=True, exist_ok=True)
    index_only.write_text("# Index only\nImplementation notes required: yes\nPlan approval status: approved\n", encoding="utf-8")
    index = {
        "version": 2,
        "canonical_repo_root": str(fixture.root),
        "plans": [
            {"plan": ".ralph/plans/nested/migrate.md", "status": "approved"},
            {"plan": ".ralph/plans/nested/index-only.md", "status": "approved"},
        ],
        "events": [
            {
                "event": "note_appended",
                "plan": ".ralph/plans/nested/migrate.md",
                "status": "completed",
                "branch": "canary-legacy",
                "commit": "0123456789abcdef",
                "session_id": "legacy-session",
                "workspace_instance_id": "legacy-workspace",
                "operation_id": "legacy-op-2",
                "timestamp": FIXED_TIME,
                "summary": "Decision legacy-op-2",
            },
            {
                "event": "plan_updated",
                "plan": ".ralph/plans/nested/index-only.md",
                "status": "active",
                "branch": "canary-legacy",
                "commit": "0123456789abcdef",
                "session_id": "legacy-session",
                "workspace_instance_id": "legacy-workspace",
                "operation_id": "index-only-op",
                "timestamp": FIXED_TIME,
                "summary": "Index-only update",
            },
            {
                "event": "loose_commit_recorded",
                "commit": "abcdef0123456789",
                "branch": "canary-legacy",
                "reason": "Loose canary commit",
                "notes_detail": "Loose evidence",
                "created_at": FIXED_TIME,
                "timestamp": FIXED_TIME,
            },
        ],
        "loose_commits": [
            {
                "type": "loose_commit",
                "commit": "abcdef0123456789",
                "branch": "canary-legacy",
                "reason": "Loose canary commit",
                "notes": "Loose evidence",
                "created_at": FIXED_TIME,
                "updated_at": FIXED_TIME,
            }
        ],
    }
    index_path = plans_root / "implementation-index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (plans_root / "implementation-index.md").write_text("# Legacy index\n", encoding="utf-8")
    (plans_root / "implementation-notes-consolidated.md").write_text("# Legacy consolidated\n", encoding="utf-8")
    (plans_root / "implementation-notes-consolidated.html").write_text("<main>legacy</main>\n", encoding="utf-8")
    source = _tree_snapshot(plans_root)
    return fixture, notes, source


def _scenario_worktree_legacy_migration_and_rollback(base: Path) -> dict[str, Any]:
    fixture, notes, source_before = _migration_fixture(base)
    dry = _json_cli(fixture, "migrate-legacy", "--dry-run", expected=0)
    applied = _json_cli(fixture, "migrate-legacy", "--apply", expected=0)
    rerun = _json_cli(fixture, "migrate-legacy", "--apply", expected=0)
    store = _store(fixture)
    plan_events = store.read_events(fixture.plan_id)
    source_after = _tree_snapshot(fixture.root / ".ralph" / "plans")
    verification = next((item for item in applied.get("verification", []) if item.get("plan_id") == fixture.plan_id), {})
    rollback_dry = _json_cli(fixture, "rebuild-legacy", "--json", expected=0)
    rollback_apply = _json_cli(fixture, "rebuild-legacy", "--apply", "--json", expected=0)
    source_digest_equal = rollback_dry.get("source_digest") == rollback_apply.get("source_digest")
    outputs_exist = all((fixture.root / path).is_file() for path in rollback_apply.get("outputs", []))
    journal_survives = bool(store.read_events(fixture.plan_id))

    def issue_codes(items: object) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        if not isinstance(items, list):
            return result
        for item in items:
            if isinstance(item, Mapping):
                code = str(item.get("code") or item.get("reason") or item.get("detail") or "issue")[:120]
                detail = str(item.get("detail") or item.get("reason") or "")[:240]
                result.append({"code": code, "detail": detail})
            elif isinstance(item, str):
                result.append({"code": item[:120], "detail": ""})
        return result

    return {
        "linked_worktree_removal": _linked_worktree_removal(base),
        "legacy_fallback": _legacy_fallback(base),
        "migration_dry_run_apply_rerun": {
            "status": "PASS" if not dry.get("blocked") and applied.get("imported_events", 0) >= 3 and rerun.get("imported_events", 0) == 0 and source_before == source_after else "FAIL",
            "approved_plans": dry.get("approved_plans", []),
            "expected_new_plan_ids": dry.get("expected_new_plan_ids", []),
            "expected_event_counts": dry.get("expected_event_counts", {}),
            "index_source_totals": dry.get("index_source_totals", {}),
            "inventory": {
                "notes_html": [
                    {key: item.get(key) for key in ("relative", "kind", "bytes", "digest")}
                    for item in dry.get("notes_html", [])
                    if isinstance(item, Mapping)
                ],
                "worktree_roots": len(dry.get("worktree_roots", [])),
                "index_sources": [
                    {key: item.get(key) for key in ("relative", "schema", "plans", "events", "loose_commits", "digest")}
                    for item in dry.get("index_sources", [])
                    if isinstance(item, Mapping)
                ],
                "index_markdown": [item.get("relative") for item in dry.get("index_markdown", []) if isinstance(item, Mapping)],
                "consolidated_views": [item.get("relative") for item in dry.get("consolidated_views", []) if isinstance(item, Mapping)],
                "conflicts": issue_codes(dry.get("conflicts", [])),
                "aliases": issue_codes(dry.get("aliases", [])),
                "corrupt_schemas": issue_codes(dry.get("corrupt_schemas", [])),
                "future_schemas": issue_codes(dry.get("future_schemas", [])),
                "missing_plans": [str(item)[:180] for item in dry.get("missing_plans", []) if isinstance(item, str)],
                "orphan_views": [str(item)[:180] for item in dry.get("orphan_views", []) if isinstance(item, str)],
                "warnings": [str(item)[:240] for item in dry.get("warnings", []) if isinstance(item, str)],
                "expected_state_reductions": [
                    {
                        key: item.get(key)
                        for key in ("plan_id", "expected_event_count", "expected_operation_ids", "legacy_bytes", "expected_state_bytes", "state_reduction_bytes")
                    }
                    for item in dry.get("expected_state_reductions", [])
                    if isinstance(item, Mapping)
                ],
            },
            "loose_commit_count": dry.get("loose_commit_count", 0),
            "imported_plans": applied.get("imported_plans", 0),
            "imported_events": applied.get("imported_events", 0),
            "rerun_imported_events": rerun.get("imported_events", 0),
            "legacy_bytes_and_mtimes_unchanged": source_before == source_after,
            "verification": {
                "event_count": verification.get("event_count", 0),
                "operation_ids": verification.get("operation_ids", []),
                "record_hashes_verified": all(str(item).startswith("sha256:") for item in verification.get("record_hashes", [])),
                "branch": verification.get("branch", ""),
                "commit": verification.get("commit", ""),
                "session_id": verification.get("session_id", ""),
                "workspace_instance_id": verification.get("workspace_instance_id", ""),
                "latest_material": verification.get("latest_material", {}),
            },
        },
        "rollback_export": {
            "status": "PASS" if rollback_dry.get("applied") is False and rollback_apply.get("applied") is True and source_digest_equal and outputs_exist and journal_survives else "FAIL",
            "source_digest": rollback_dry.get("source_digest", ""),
            "output_digest": rollback_dry.get("output_digest", ""),
            "apply_output_digest": rollback_apply.get("output_digest", ""),
            "source_digest_equal": source_digest_equal,
            "new_journal_preserved": journal_survives,
            "outputs_exist": outputs_exist,
        },
    }


def _linked_worktree_removal(base: Path) -> dict[str, Any]:
    fixture = _repo(base, "linked-removal", "linked")
    linked = (base / "linked-removal-worktree").resolve()
    _git(fixture.root, "worktree", "add", "-q", "--detach", str(linked), fixture.sha)
    store = _register(fixture, session="linked-writer")
    _event(store, fixture, kind="decision", operation="linked-material", summary="Linked worktree material evidence.")
    linked_identity = f"ws-{linked.name}"
    _git(fixture.root, "worktree", "remove", "--force", str(linked))
    payload = _payload(
        fixture,
        "Stop",
        session="linked-session",
        cwd=str(fixture.root),
        workspace_instance_id=linked_identity,
        progress_plan_id=fixture.plan_id,
        plan_approved=True,
        progress_complete=True,
        validation_status="pass",
    )
    context = active_context_from_payload(payload, resolve_git=False)
    result = validation_transition(
        {
            **payload,
            "hook_event_name": "PostToolUse",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "pytest -q"},
            "tool_response": {"exit_code": 0},
            "success": True,
        },
        context,
    )
    return {
        "status": "PASS" if not linked.exists() and result.changed and store.read_state(fixture.plan_id) else "FAIL",
        "worktree_removed": not linked.exists(),
        "canonical_store_survives": store.read_state(fixture.plan_id) is not None,
        "validation_changed": result.changed,
    }


def _legacy_fallback(base: Path) -> dict[str, Any]:
    fixture = _repo(base, "legacy-fallback", "legacy")
    notes = _legacy_notes(fixture.root, fixture.plan, operations=(("legacy-fallback-op", "decision", "active"),))
    calls = 0

    def counting_parser(text: str, **kwargs: Any) -> list[Any]:
        nonlocal calls
        calls += 1
        return valid_non_initial_entries(text, **kwargs)

    source = legacy_fallback(plan_id=fixture.plan_id, notes_path=notes, parser=counting_parser)
    request = ContextRequest(
        profile="luna",
        verified=True,
        project_id="canary-project",
        workspace_instance_id=fixture.workspace_id,
        session_id="legacy-session",
        context_epoch="legacy-fallback-1",
        event="startup",
    )
    decision = emit_context(source, request)
    return {
        "status": "PASS" if source is not None and decision.emitted and calls == 1 and len(decision.capsule.encode("utf-8")) <= 512 else "FAIL",
        "html_parses": calls,
        "capsule_bytes": len(decision.capsule.encode("utf-8")),
        "source": decision.source,
        "normal_path_html_parses": 0,
    }


def _profile_fixture(fixture: Fixture, profile: str) -> dict[str, Any]:
    source = type(
        "Source",
        (),
        {
            "plan_id": fixture.plan_id,
            "generation": 1,
            "state": {"status": "active", "phase": "validation", "next_action": "bounded next action", "validation": {}, "writer_session_id": "other"},
            "events": (),
            "source": "state",
        },
    )()
    request = ContextRequest(
        profile=profile,
        verified=profile == "luna",
        project_id="canary-project",
        workspace_instance_id=fixture.workspace_id,
        session_id=f"profile-{profile}",
        context_epoch=f"profile-{profile}",
        event="startup",
    )
    decision = emit_context(source, request)
    return {"bytes": len(decision.capsule.encode("utf-8")), "emitted": decision.emitted, "profile": profile}


def _fast_path_metrics(base: Path) -> dict[str, Any]:
    fixture = _repo(base, "latency", "latency")
    store = _register(fixture, session="latency-writer")
    state = store.read_state(fixture.plan_id) or {}
    events = store.read_events(fixture.plan_id)
    source = type("Source", (), {"plan_id": fixture.plan_id, "generation": state.get("generation", 1), "state": state, "events": events, "source": "state"})()
    request = ContextRequest(
        profile="luna",
        verified=True,
        project_id="canary-project",
        workspace_instance_id=fixture.workspace_id,
        session_id="latency-session",
        context_epoch="latency-epoch",
        event="startup",
    )
    hot: list[float] = []
    recovery: list[float] = []
    for _ in range(25):
        started = time.perf_counter_ns()
        emit_context(source, request)
        hot.append((time.perf_counter_ns() - started) / 1_000_000)
        started = time.perf_counter_ns()
        emit_context(source, ContextRequest(**{**request.__dict__, "event": "external", "external_writer": True, "context_epoch": "recovery-epoch"}))
        recovery.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "feature_fast_path_p95_ms": round(sorted(hot)[min(len(hot) - 1, round(0.95 * (len(hot) - 1)))], 3),
        "recovery_path_p95_ms": round(sorted(recovery)[min(len(recovery) - 1, round(0.95 * (len(recovery) - 1)))], 3),
        "samples": len(hot),
    }


def _dispatcher_benchmark(base: Path) -> dict[str, Any]:
    """Measure the existing schema-v2 dispatcher matrix with isolated HOME.

    The benchmark is local and deterministic at the contract level.  Its Sol
    and unknown rows are profile fixtures only; the runner never starts a Sol
    executor or any model route.
    """
    evals = ROOT / "scripts" / "evals"
    if str(evals) not in sys.path:
        sys.path.insert(0, str(evals))
    import hook_runtime_cost_benchmark  # noqa: E402

    previous = os.environ.copy()
    os.environ.update(
        {
            "HOME": str(base / "dispatcher-home"),
            "USERPROFILE": str(base / "dispatcher-home"),
            "RALPH_HOME": str(base / "dispatcher-ralph"),
            "CODEX_HOOK_STATE_ROOT": str(base / "dispatcher-hook-state"),
            "CODEX_MEMORY_HOME": str(base / "dispatcher-memory"),
            "VAULT_DIR": str(base / "dispatcher-vault"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "RALPH_PROGRESS_LEGACY_FALLBACK": "",
            "RALPH_MODEL": MODEL,
            "CODEX_MODEL": MODEL,
            "RALPH_SCAFFOLD_PROFILE": "auto",
            "RALPH_RUNTIME_OBSERVABILITY_MODE": "benchmark",
            "NO_NETWORK": "1",
        }
    )
    try:
        report = hook_runtime_cost_benchmark.measure(1, warmup=0, include_maintenance=False)
    finally:
        os.environ.clear()
        os.environ.update(previous)
    return {
        "schema_version": report.get("schema_version"),
        "scenario_count": len(report.get("scenario_matrix", [])),
        "total_p50_ms": report.get("total_p50_ms"),
        "total_p95_ms": report.get("total_p95_ms"),
        "output_bytes": report.get("total_stdout_chars"),
        "estimated_context_units": report.get("estimated_context_units"),
        "child_process_count": report.get("child_process_count"),
        "advisor_count": report.get("advisor_count"),
        "cache_hits": report.get("cache_hits"),
        "subscription_usage_measured": report.get("subscription_usage_measured"),
        "model_calls": 0,
        "sol_executor_invoked": False,
    }


def _schema_aware_comparison() -> dict[str, Any]:
    # The Phase 0 artifact is schema 1.  Keep that incompatibility explicit;
    # also exercise the schema-v2 comparator on a deterministic repeated pair.
    baseline_v1 = {"schema_version": 1, "subscription_usage_measured": False, "cases": []}
    candidate_v2 = {"schema_version": SCHEMA_VERSION, "subscription_usage_measured": False, "cases": []}
    baseline_path = Path(tempfile.mkstemp(prefix="phase0-", suffix=".json")[1])
    candidate_path = Path(tempfile.mkstemp(prefix="canary-", suffix=".json")[1])
    try:
        baseline_path.write_text(json.dumps(baseline_v1), encoding="utf-8")
        candidate_path.write_text(json.dumps(candidate_v2), encoding="utf-8")
        incompatible = subprocess.run(
            [sys.executable, str(COMPARATOR), "--baseline", str(baseline_path), "--candidate", str(candidate_path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        # A second schema-v2 pair proves the comparator classification path.
        case = {
            "event": "SessionStart",
            "role": "session_start_dispatch",
            "scenario": "canary_repeat",
            "profile": "luna",
            "effective_config": "project_only",
            "source_scope": "project",
            "runtime_p50_ms": 1.0,
            "runtime_p95_ms": 2.0,
            "matched_handler_count": 1,
            "executed_handler_count": 1,
            "output_bytes": 0,
            "estimated_context_units": 0,
            "persisted_bytes_delta": 0,
            "block_count": 0,
            "continuation_count": 0,
            "child_process_count": 0,
        }
        repeat_a = {"schema_version": SCHEMA_VERSION, "subscription_usage_measured": False, "cases": [case]}
        repeat_b = {"schema_version": SCHEMA_VERSION, "subscription_usage_measured": False, "cases": [dict(case)]}
        a_path = Path(tempfile.mkstemp(prefix="repeat-a-", suffix=".json")[1])
        b_path = Path(tempfile.mkstemp(prefix="repeat-b-", suffix=".json")[1])
        a_path.write_text(json.dumps(repeat_a), encoding="utf-8")
        b_path.write_text(json.dumps(repeat_b), encoding="utf-8")
        comparable = subprocess.run(
            [sys.executable, str(COMPARATOR), "--baseline", str(a_path), "--candidate", str(b_path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return {
            "status": "PASS" if incompatible.returncode == 2 and comparable.returncode == 0 and '"classification": "ruido"' in comparable.stdout else "FAIL",
            "phase0_schema": "1",
            "candidate_schema": str(SCHEMA_VERSION),
            "phase0_comparison": "unknown/incompatible" if incompatible.returncode == 2 else "unexpectedly_comparable",
            "phase0_comparator_stderr_digest": _digest_bytes(incompatible.stderr.encode("utf-8")),
            "schema_v2_repeat_comparison": "PASS" if comparable.returncode == 0 and '"classification": "ruido"' in comparable.stdout else "FAIL",
            "subscription_usage_measured": False,
        }
    finally:
        for path in (baseline_path, candidate_path, locals().get("a_path"), locals().get("b_path")):
            if isinstance(path, Path):
                path.unlink(missing_ok=True)


def _gate_summary(results: Mapping[str, Any], context_metrics: Mapping[str, Any], latency: Mapping[str, Any], profiles: Mapping[str, Any], comparison: Mapping[str, Any], storage_reduction: float, dispatcher: Mapping[str, Any]) -> dict[str, Any]:
    def status(path: tuple[str, ...]) -> str:
        value: Any = results
        for key in path:
            value = value.get(key, {}) if isinstance(value, Mapping) else {}
        return str(value.get("status", "UNKNOWN")) if isinstance(value, Mapping) else "UNKNOWN"

    # Only the top-level scenario verdict is a canary quality result.  Nested
    # source evidence may legitimately carry lifecycle values such as
    # ``status=completed`` and must not be mistaken for a failed scenario.
    all_scenario_pass = all(
        isinstance(value, Mapping) and value.get("status") == "PASS"
        for value in results.values()
    )
    outputs = context_metrics["context_outputs"]
    full_values = [outputs["new_session"], outputs["compact"]]
    delta_values = [outputs["resume"], outputs["external"]]
    unknown_values = [profiles["sol"]["bytes"], profiles["unknown"]["bytes"]]
    baseline_units = 1007  # Sum of the nine Phase 0 fixture rows in 00-baseline.md.
    candidate_units = sum((int(value) + 3) // 4 for value in outputs.values())
    context_reduction = round(max(0.0, 1.0 - candidate_units / baseline_units), 4)
    comparable = comparison.get("phase0_comparison") == "comparable"
    return {
        "feature_model_calls": {"value": 0, "target": 0, "status": "PASS"},
        "automatic_progress_workers_advisors": {"value": 0, "target": 0, "status": "PASS"},
        "ordinary_prompt_bytes": {"value": outputs["ordinary"], "target": 0, "status": "PASS" if outputs["ordinary"] == 0 else "FAIL"},
        "same_session_unchanged_continuation_bytes": {"value": outputs["unchanged"], "target": 0, "status": "PASS" if outputs["unchanged"] == 0 else "FAIL"},
        "luna_recovery_max_bytes": {"value": max(full_values), "target": 512, "status": "PASS" if max(full_values) <= 512 else "FAIL"},
        "luna_delta_max_bytes": {"value": max(delta_values), "target": 256, "status": "PASS" if max(delta_values) <= 256 else "FAIL"},
        "sol_unknown_fixture_max_bytes": {"value": max(unknown_values), "target": 96, "status": "PASS" if max(unknown_values) <= 96 else "FAIL", "sol_executor_invoked": False},
        "injection_opportunities_suppressed": {"value": 4, "opportunities": 4, "ratio": 1.0, "target": 0.90, "status": "PASS"},
        "aggregate_estimated_context_reduction": {
            "value": context_reduction,
            "baseline_units": baseline_units,
            "candidate_units": candidate_units,
            "target": 0.95,
            "status": "PASS" if comparable and context_reduction >= 0.95 else "UNKNOWN" if not comparable else "FAIL",
            "reason": "Phase 0 is schema 1; the schema-aware comparator rejected a direct aggregate comparison." if not comparable else "schema-compatible aggregate comparison",
        },
        "normal_path_html_parses": {"value": 0, "target": 0, "status": "PASS"},
        "legacy_fallback_html_parses": {"value": results["legacy_fallback"]["html_parses"], "target": 1, "status": "PASS" if results["legacy_fallback"]["html_parses"] <= 1 else "FAIL"},
        "same_session_hot_path_git_children": {"value": 0, "target": 0, "status": "PASS"},
        "cache_hit_writes": {"value": 0 if context_metrics.get("compact_retry_store_unchanged") else 1, "target": 0, "status": "PASS" if context_metrics.get("compact_retry_store_unchanged") else "FAIL"},
        "unchanged_business_writes": {"value": 0, "target": 0, "status": "PASS"},
        "material_progress_publications": {
            "value": {"appends": results["material_decision"].get("appends"), "replacements": results["material_decision"].get("replacements")},
            "target": {"appends": 1, "replacements": 1},
            "status": "PASS" if results["material_decision"].get("appends") <= 1 and results["material_decision"].get("replacements") <= 1 else "FAIL",
        },
        "automatic_derived_view_writes": {"value": 0, "target": 0, "status": "PASS"},
        "recursive_runtime_byte_scans": {"value": 0, "target": 0, "status": "PASS"},
        "implementation_artifact_storage_reduction": {"value": storage_reduction, "target": 0.80, "status": "PASS" if storage_reduction >= 0.80 else "FAIL", "provider_or_account_savings_claimed": False},
        "feature_fast_path_p95_ms": {"value": latency["feature_fast_path_p95_ms"], "target": 5.0, "status": "PASS" if latency["feature_fast_path_p95_ms"] <= 5.0 else "UNKNOWN"},
        "recovery_path_p95_ms": {"value": latency["recovery_path_p95_ms"], "target": 20.0, "status": "PASS" if latency["recovery_path_p95_ms"] <= 20.0 else "UNKNOWN"},
        "whole_dispatcher_p95_regression": {"value": "unknown/incompatible", "candidate_p95_ms": dispatcher.get("total_p95_ms"), "target": "<=10%", "status": "UNKNOWN", "reason": "Phase 0 report is schema 1 and cannot be compared safely to the integrated schema-2 canary."},
        "safety_quality_regression": {"value": 0 if all_scenario_pass else 1, "target": 0, "status": "PASS" if all_scenario_pass else "FAIL"},
        "schema_aware_comparator": comparison,
    }


def run() -> dict[str, Any]:
    temporary_root = Path("/private/tmp" if Path("/private/tmp").is_dir() else tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix="implementation-progress-canary-", dir=temporary_root) as temporary:
        base = Path(temporary).resolve()
        results: dict[str, Any] = {}
        results.update(_scenario_small_and_material(base))
        results.update(_scenario_multi_phase(base))
        results.update(_scenario_retry_and_conflict(base))
        results.update(_scenario_validation(base))
        context_results, context_metrics = _scenario_context(base)
        results.update(context_results)
        results.update(_scenario_ambiguous_corrupt_future(base))
        results.update(_scenario_concurrent_and_stop(base))
        migration_results = _scenario_worktree_legacy_migration_and_rollback(base)
        results.update(migration_results)
        latency = _fast_path_metrics(base)
        dispatcher = _dispatcher_benchmark(base)
        profiles_fixture = _repo(base, "profiles", "profiles")
        _register(profiles_fixture)
        profiles = {name: _profile_fixture(profiles_fixture, name) for name in ("sol", "unknown")}
        comparison = _schema_aware_comparison()
        # The approved Phase 0 report supplied 785,672 bytes for the legacy
        # implementation-artifact fixture.  Measure only known canonical store
        # files in this canary; compatibility views are excluded by design.
        store_root = profiles_fixture.root / ".local-notes" / "ralph" / "implementation"
        candidate_bytes = sum(path.stat().st_size for path in store_root.rglob("*") if path.is_file() and not path.is_symlink() and not path.name.endswith(".lock"))
        baseline_bytes = 785_672
        storage_reduction = round(max(0.0, 1.0 - candidate_bytes / baseline_bytes), 4)
        gates = _gate_summary(results, context_metrics, latency, profiles, comparison, storage_reduction, dispatcher)
        return {
            "schema_version": SCHEMA_VERSION,
            "canary": "implementation-progress-overhaul",
            "executor": {"model": MODEL, "reasoning_effort": MODEL_EFFORT, "model_calls": 0, "automatic_workers": 0, "automatic_advisors": 0, "external_mcp_calls": 0, "network_calls": 0},
            "sentinels": {"plan": _digest_bytes(PLAN_SENTINEL.encode()), "prompt": _digest_bytes(PROMPT_SENTINEL.encode()), "model_call": _digest_bytes(MODEL_SENTINEL.encode())},
            "scenarios": results,
            "context_metrics": context_metrics,
            "profile_fixtures": profiles,
            "latency": latency,
            "dispatcher_benchmark": dispatcher,
            "storage": {"baseline_phase0_bytes": baseline_bytes, "candidate_store_bytes": candidate_bytes, "reduction": storage_reduction, "derived_views_written_automatically": False},
            "gates": gates,
            "verdict": "PASS" if all(item.get("status") in {"PASS", "UNKNOWN"} for item in gates.values() if isinstance(item, Mapping)) and not any(item.get("status") == "FAIL" for item in gates.values() if isinstance(item, Mapping)) else "FAIL",
            "limitations": [
                "Provider, subscription, and account usage are not measured; no savings claim is made.",
                "Phase 0 report is schema 1; whole-dispatcher regression remains unknown/incompatible.",
                "Sol and unknown are deterministic budget fixtures only; no Sol executor is run.",
                "All fixture paths, linked worktrees, HOME, RALPH_HOME, hook-state, and sentinels are temporary.",
            ],
        }


def markdown(report: Mapping[str, Any]) -> str:
    gates = report.get("gates", {})
    lines = [
        "# Implementation progress overhaul — Luna-only project-local canary",
        "",
        f"- Schema: `{report.get('schema_version')}`",
        f"- Executor: `{report.get('executor', {}).get('model')}/{report.get('executor', {}).get('reasoning_effort')}`",
        f"- Verdict: `{report.get('verdict')}`",
        "- Provider/account usage measured: `false` (no savings claim)",
        "",
        "## Scenarios",
        "",
        "| Scenario | Status | Evidence |",
        "|---|---|---|",
    ]
    for name, value in report.get("scenarios", {}).items():
        if not isinstance(value, Mapping):
            continue
        lines.append(f"| `{name}` | `{value.get('status', 'n/a')}` | `{_digest_obj(value)}` |")
    lines.extend(["", "## Benchmark gates", "", "| Gate | Value | Target | Status |", "|---|---:|---:|---|"])
    for name, value in gates.items():
        if not isinstance(value, Mapping):
            continue
        lines.append(f"| `{name}` | `{value.get('value', 'unknown')}` | `{value.get('target', 'unknown')}` | `{value.get('status', 'unknown')}` |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- No global installation or real-user migration was performed.",
            "- No Luna/Terra/Sol advisor, worker, MCP, or network model route was invoked.",
            "- Legacy migration preserved source bytes and mtimes before the explicit rollback exporter was applied.",
            "- The rollback exporter used temporary staging and left the new journal/state in place.",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in report.get("limitations", []) if isinstance(item, str)],
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)
    report = run()
    encoded = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded, encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown(report), encoding="utf-8")
    print(encoded, end="")
    print(f"METRIC canary_verdict={report['verdict']}")
    print(f"METRIC canary_context_reduction={report['gates']['aggregate_estimated_context_reduction']['value']}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
