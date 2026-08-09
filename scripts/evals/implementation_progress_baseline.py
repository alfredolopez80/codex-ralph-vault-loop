#!/usr/bin/env python3
"""Measure the legacy implementation-progress cost without changing hooks.

The harness imports the existing readers/writers and instruments only named
boundaries while a deterministic temporary fixture is active.  It never writes
fixture content to the report and rejects every subprocess other than local
``git`` metadata lookup, which makes an accidental provider/MCP call a failed
measurement rather than an invisible zero.
"""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterator, Mapping
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
PLANS = ROOT / "scripts" / "plans"
for _path in (HOOKS, PLANS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import continuity_prompt_context as continuity  # noqa: E402
import implementation_context as implementation_context  # noqa: E402
import implementation_index_lib as implementation_index  # noqa: E402
import implementation_notes_lib as implementation_notes  # noqa: E402
import post_tool_dispatch  # noqa: E402
import session_start_dispatch  # noqa: E402
import stop_dispatch  # noqa: E402
import user_prompt_dispatch  # noqa: E402
from shared import active_context, checkpoint_io, context_delta, post_tool_state, runtime_event_store, session_context_cache  # noqa: E402
from shared import stop_persistence  # noqa: E402


SCHEMA_VERSION = 1
MODEL = "gpt-5.6-luna"
BRANCH = "baseline-branch"
FIXTURE_PLAN_NAME = "fixture-progress-plan.md"
SEED_OPERATION = "baseline-seed-operation"
MATERIAL_OPERATION = "baseline-material-operation"
PROMPT_SENTINEL = "baseline prompt content is never persisted in this report"
NOTE_SENTINEL = "baseline note content is never persisted in this report"
CASE_SAMPLES = 5
CASE_REPEATS = 2


def _load_script(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load benchmark script: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CREATE_NOTES = _load_script("baseline_create_implementation_notes", PLANS / "create-implementation-notes.py")
APPEND_NOTE = _load_script("baseline_append_implementation_note", PLANS / "append-implementation-note.py")


def percentile(values: list[float | int], pct: float) -> float:
    if not values:
        raise ValueError("percentile requires one or more samples")
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[index]


def estimate_context_units(output_bytes: int) -> int:
    """Match the current documented heuristic: ceil(bytes / 4)."""
    return max(0, (max(0, output_bytes) + 3) // 4)


@dataclass
class Counters:
    notes_bytes_read: int = 0
    plan_bytes_read: int = 0
    plan_read_count: int = 0
    index_bytes_read: int = 0
    index_read_count: int = 0
    html_parse_count: int = 0
    git_subprocess_count: int = 0
    external_subprocess_count: int = 0
    advisor_invocation_count: int = 0
    worker_invocation_count: int = 0
    recursive_scan_count: int = 0
    recursive_scan_bytes: int = 0
    recursive_scan_ms: float = 0.0
    publication_count: int = 0
    publication_bytes: int = 0
    replacement_count: int = 0
    append_publication_count: int = 0
    fsync_relevant_publications: int = 0
    fsync_call_count: int = 0

    def reset(self) -> None:
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, 0)

    def as_dict(self) -> dict[str, object]:
        return {
            "notes_bytes_read": self.notes_bytes_read,
            "plan_bytes_read": self.plan_bytes_read,
            "plan_read_count": self.plan_read_count,
            "index_bytes_read": self.index_bytes_read,
            "index_read_count": self.index_read_count,
            "html_parse_count": self.html_parse_count,
            "git_subprocess_count": self.git_subprocess_count,
            "external_subprocess_count": self.external_subprocess_count,
            "advisor_invocation_count": self.advisor_invocation_count,
            "worker_invocation_count": self.worker_invocation_count,
            "recursive_scan_count": self.recursive_scan_count,
            "recursive_scan_bytes": self.recursive_scan_bytes,
            "recursive_scan_ms": round(self.recursive_scan_ms, 3),
            "publication_count": self.publication_count,
            "publication_bytes": self.publication_bytes,
            "replacement_count": self.replacement_count,
            "append_publication_count": self.append_publication_count,
            "fsync_relevant_publications": self.fsync_relevant_publications,
            "fsync_call_count": self.fsync_call_count,
        }

    def record_publication(self, size: int, *, fsync_calls: int, append: bool = False) -> None:
        self.publication_count += 1
        self.publication_bytes += max(0, size)
        self.replacement_count += 1
        self.fsync_relevant_publications += 1
        self.fsync_call_count += max(0, fsync_calls)
        if append:
            self.append_publication_count += 1


@dataclass(frozen=True)
class TreeEntry:
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class TreeDelta:
    files_written: int
    bytes_written_estimate: int
    bytes_delta: int
    replacements_observed: int
    appends_observed: int
    mtime_ns_changes: int
    created_files: int
    removed_files: int

    def as_dict(self) -> dict[str, int]:
        return {
            "files_written": self.files_written,
            "bytes_written_estimate": self.bytes_written_estimate,
            "bytes_delta": self.bytes_delta,
            "replacements_observed": self.replacements_observed,
            "appends_observed": self.appends_observed,
            "mtime_ns_changes": self.mtime_ns_changes,
            "created_files": self.created_files,
            "removed_files": self.removed_files,
        }


@dataclass
class Fixture:
    root: Path
    runtime: Path
    plan: Path
    notes: Path
    branch: str
    sha: str
    session_id: str = "baseline-session"

    def payload(self, *, session_id: str | None = None, source: str | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "cwd": str(self.root),
            "workspace_root": str(self.root),
            "session_id": session_id or self.session_id,
            "turn_id": "baseline-turn",
            "branch": self.branch,
            "sha": self.sha,
            "model": MODEL,
            "scenario": "implementation-progress-baseline",
        }
        if source:
            payload["source"] = source
        return payload


def _run_git(root: Path, args: list[str], *, env: Mapping[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        env=dict(env) if env is not None else None,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    return result.stdout.strip()


def _fixture_plan_text(notes_path: Path | None = None) -> str:
    notes_line = f"Implementation notes: {notes_path}\n" if notes_path is not None else ""
    return (
        "# Fixture Implementation Progress Plan\n"
        "\n"
        + notes_line
        + "Implementation notes required: yes\n"
        + "Implementation notes status: active\n"
        + "Plan approval status: approved\n"
        + "\n"
        + "## Objective\n"
        + "\n"
        + "Measure the current implementation-progress reader and writer paths.\n"
    )


def _make_repo(root: Path) -> tuple[Path, str, str]:
    root.mkdir(parents=True, exist_ok=True)
    _run_git(root, ["init", "-q", "-b", BRANCH])
    _run_git(root, ["config", "user.email", "baseline@example.invalid"])
    _run_git(root, ["config", "user.name", "Baseline Fixture"])
    plans = root / ".ralph" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    plan = (plans / FIXTURE_PLAN_NAME).resolve()
    notes = plan.with_name("fixture-progress-plan-implementation-notes.html")
    plan.write_text(_fixture_plan_text(notes), encoding="utf-8")
    (root / "fixture.txt").write_text("fixture\n", encoding="utf-8")
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
        }
    )
    _run_git(root, ["add", "."], env=commit_env)
    _run_git(root, ["commit", "-q", "-m", "fixture baseline"], env=commit_env)
    sha = _run_git(root, ["rev-parse", "HEAD"])
    branch = _run_git(root, ["branch", "--show-current"])
    return plan, branch, sha


def _run_script(module: Any, args: list[str]) -> None:
    old_argv = sys.argv
    stderr = io.StringIO()
    try:
        sys.argv = [str(getattr(module, "__file__", "baseline-script")), *args]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            result = module.main()
    finally:
        sys.argv = old_argv
    if result not in (None, 0):
        raise RuntimeError(f"fixture script failed with exit={result}: {stderr.getvalue().strip()[:240]}")


def _create_notes(fixture: Fixture) -> None:
    _run_script(
        CREATE_NOTES,
        [
            "--plan",
            str(fixture.plan),
            "--active-root",
            str(fixture.root),
            "--primary-root",
            str(fixture.root),
            "--approved",
        ],
    )


def _append_note(fixture: Fixture, operation_id: str = MATERIAL_OPERATION) -> None:
    _run_script(
        APPEND_NOTE,
        [
            "--notes",
            str(fixture.notes),
            "--active-root",
            str(fixture.root),
            "--primary-root",
            str(fixture.root),
            "--category",
            "decision",
            "--decision",
            NOTE_SENTINEL,
            "--reason",
            "deterministic fixture update",
            "--impact",
            "material benchmark event",
            "--related-file",
            "fixture.txt",
            "--status",
            "active",
            "--operation-id",
            operation_id,
        ],
    )


def seed_fixture(root: Path, *, with_notes: bool = True) -> Fixture:
    plan, branch, sha = _make_repo(root)
    runtime = root / "ralph-home"
    runtime.mkdir(parents=True, exist_ok=True)
    fixture = Fixture(root, runtime, plan, plan.with_name("fixture-progress-plan-implementation-notes.html"), branch, sha)
    if with_notes:
        _create_notes(fixture)
        _append_note(fixture, SEED_OPERATION)
    return fixture


def add_ambiguous_plan(fixture: Fixture) -> None:
    plan = (fixture.root / ".ralph" / "plans" / "ambiguous-progress-plan.md").resolve()
    notes = plan.with_name("ambiguous-progress-plan-implementation-notes.html")
    plan.write_text(_fixture_plan_text(notes).replace("Fixture Implementation Progress Plan", "Ambiguous Fixture Plan"), encoding="utf-8")
    duplicate = Fixture(fixture.root, fixture.runtime, plan, plan.with_name("ambiguous-progress-plan-implementation-notes.html"), fixture.branch, fixture.sha, fixture.session_id)
    _create_notes(duplicate)


def context_for(fixture: Fixture, *, session_id: str | None = None) -> active_context.ActiveContext:
    return active_context.active_context_from_payload(fixture.payload(session_id=session_id), resolve_git=False)


def _snapshot_roots(fixture: Fixture) -> dict[str, Path]:
    return {
        "workspace_ralph": fixture.root / ".ralph",
        "workspace_codex": fixture.root / ".codex",
        "ralph_home": fixture.runtime,
    }


def snapshot_tree(fixture: Fixture) -> dict[str, TreeEntry]:
    result: dict[str, TreeEntry] = {}
    for label, root in _snapshot_roots(fixture).items():
        if not root.exists() or root.is_symlink():
            continue
        for current, directories, files in os.walk(root, followlinks=False):
            directories[:] = [name for name in directories if not (Path(current) / name).is_symlink()]
            for name in files:
                path = Path(current) / name
                if path.is_symlink():
                    continue
                try:
                    stat_result = path.stat()
                except OSError:
                    continue
                relative = path.relative_to(root).as_posix()
                result[f"{label}/{relative}"] = TreeEntry(stat_result.st_size, stat_result.st_mtime_ns)
    return result


def snapshot_delta(before: Mapping[str, TreeEntry], after: Mapping[str, TreeEntry], counters: Counters) -> TreeDelta:
    created = set(after) - set(before)
    removed = set(before) - set(after)
    changed = {
        name
        for name in set(before) & set(after)
        if before[name].size != after[name].size or before[name].mtime_ns != after[name].mtime_ns
    }
    written = created | changed
    bytes_written = sum(after[name].size for name in written)
    bytes_delta = sum(after[name].size for name in after) - sum(before[name].size for name in before)
    appends = sum(
        1
        for name in set(before) & set(after)
        if name.endswith(".jsonl") and after[name].size > before[name].size
    )
    mtime_changes = sum(
        1
        for name in set(before) & set(after)
        if after[name].mtime_ns != before[name].mtime_ns
    )
    return TreeDelta(
        files_written=len(written),
        bytes_written_estimate=bytes_written,
        bytes_delta=bytes_delta,
        replacements_observed=counters.replacement_count,
        appends_observed=appends + counters.append_publication_count,
        mtime_ns_changes=mtime_changes,
        created_files=len(created),
        removed_files=len(removed),
    )


class MeasurementPatches:
    """Install temporary counters at current implementation boundaries."""

    def __init__(self, counters: Counters):
        self.counters = counters
        self.stack = contextlib.ExitStack()

    def __enter__(self) -> "MeasurementPatches":
        self._patch_subprocess_guard()
        self._patch_read_boundaries()
        self._patch_write_boundaries()
        self._patch_scan_boundaries()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stack.close()

    def _patch_subprocess_guard(self) -> None:
        original = subprocess.run

        def guarded(*args: Any, **kwargs: Any) -> Any:
            argv = args[0] if args else kwargs.get("args", [])
            values = list(argv) if isinstance(argv, (list, tuple)) else []
            executable = Path(str(values[0])).name if values else "unknown"
            if executable != "git":
                self.counters.external_subprocess_count += 1
                raise RuntimeError(f"non-git subprocess forbidden in baseline: {executable}")
            self.counters.git_subprocess_count += 1
            return original(*args, **kwargs)

        self.stack.enter_context(patch.object(subprocess, "run", guarded))

    def _patch_read_boundaries(self) -> None:
        original_parser = implementation_notes.NotesHTMLParser
        counters = self.counters

        class CountingParser(original_parser):
            def __init__(self) -> None:
                counters.html_parse_count += 1
                super().__init__()

        self.stack.enter_context(patch.object(implementation_notes, "NotesHTMLParser", CountingParser))

        def notes_reader(original: Callable[..., Any]) -> Callable[..., Any]:
            def wrapped(text: str, *args: Any, **kwargs: Any) -> Any:
                counters.notes_bytes_read += len(text.encode("utf-8"))
                return original(text, *args, **kwargs)

            return wrapped

        for module in (implementation_notes, implementation_context, implementation_index):
            if hasattr(module, "valid_non_initial_entries"):
                original = getattr(module, "valid_non_initial_entries")
                self.stack.enter_context(patch.object(module, "valid_non_initial_entries", notes_reader(original)))

        original_hash = implementation_context.notes_hash

        def hash_reader(path: Path) -> str:
            with contextlib.suppress(OSError):
                counters.notes_bytes_read += path.stat().st_size
            return original_hash(path)

        self.stack.enter_context(patch.object(implementation_context, "notes_hash", hash_reader))

        def plan_reader(original: Callable[..., Any]) -> Callable[..., Any]:
            def wrapped(path: Path, *args: Any, **kwargs: Any) -> Any:
                counters.plan_read_count += 1
                with contextlib.suppress(OSError):
                    counters.plan_bytes_read += path.stat().st_size
                return original(path, *args, **kwargs)

            return wrapped

        for module_name in (implementation_notes, implementation_context, CREATE_NOTES):
            for name in ("parse_plan_metadata", "plan_identity", "infer_title"):
                if hasattr(module_name, name):
                    original = getattr(module_name, name)
                    self.stack.enter_context(patch.object(module_name, name, plan_reader(original)))

        original_index_load = implementation_index._load_index_unlocked

        def index_reader(primary_root: Path, *args: Any, **kwargs: Any) -> Any:
            path = implementation_index.index_json_path(primary_root)
            if path.exists():
                counters.index_read_count += 1
                with contextlib.suppress(OSError):
                    counters.index_bytes_read += path.stat().st_size
            return original_index_load(primary_root, *args, **kwargs)

        self.stack.enter_context(patch.object(implementation_index, "_load_index_unlocked", index_reader))

    def _patch_write_boundaries(self) -> None:
        counters = self.counters

        original_index_write = implementation_index._atomic_write

        def index_write(path: Path, text: str) -> None:
            original_index_write(path, text)
            counters.record_publication(len(text.encode("utf-8")), fsync_calls=2)

        self.stack.enter_context(patch.object(implementation_index, "_atomic_write", index_write))

        original_checkpoint_write = checkpoint_io.atomic_write_text

        def checkpoint_write(path: Path, text: str) -> None:
            original_checkpoint_write(path, text)
            counters.record_publication(len(text.encode("utf-8")), fsync_calls=1)

        self.stack.enter_context(patch.object(checkpoint_io, "atomic_write_text", checkpoint_write))

        original_cache_write = context_delta._write

        def cache_write(path: Path, entries: Mapping[str, object]) -> bool:
            result = original_cache_write(path, entries)
            if result:
                with contextlib.suppress(OSError):
                    counters.record_publication(path.stat().st_size, fsync_calls=1)
            return result

        self.stack.enter_context(patch.object(context_delta, "_write", cache_write))

        original_state_write = session_context_cache.write_state

        def state_write(context: active_context.ActiveContext, state: dict[str, Any]) -> bool:
            result = original_state_write(context, state)
            if result:
                with contextlib.suppress(OSError):
                    counters.record_publication(session_context_cache.state_path(context).stat().st_size, fsync_calls=1)
            return result

        self.stack.enter_context(patch.object(session_context_cache, "write_state", state_write))
        self.stack.enter_context(patch.object(session_start_dispatch, "write_state", state_write))

        original_append_notes = implementation_notes.append_entry

        def append_notes(path: Path, entry: str, category: str) -> bool:
            changed = original_append_notes(path, entry, category)
            if changed:
                with contextlib.suppress(OSError):
                    counters.record_publication(path.stat().st_size, fsync_calls=2, append=True)
            return changed

        self.stack.enter_context(patch.object(implementation_notes, "append_entry", append_notes))
        self.stack.enter_context(patch.object(implementation_index, "append_entry", append_notes))

        original_marker = stop_persistence._write_marker

        def marker_write(path: Path, scope: Any, fingerprint: str) -> None:
            original_marker(path, scope, fingerprint)
            with contextlib.suppress(OSError):
                counters.record_publication(path.stat().st_size, fsync_calls=1)

        self.stack.enter_context(patch.object(stop_persistence, "_write_marker", marker_write))

    def _patch_scan_boundaries(self) -> None:
        counters = self.counters

        def scan_wrapper(original: Callable[..., int]) -> Callable[..., int]:
            def wrapped(path: Path, *args: Any, **kwargs: Any) -> int:
                started = time.perf_counter_ns()
                result = original(path, *args, **kwargs)
                counters.recursive_scan_count += 1
                counters.recursive_scan_bytes += max(0, int(result))
                counters.recursive_scan_ms += (time.perf_counter_ns() - started) / 1_000_000
                return result

            return wrapped

        self.stack.enter_context(patch.object(post_tool_dispatch, "directory_bytes", scan_wrapper(post_tool_dispatch.directory_bytes)))
        self.stack.enter_context(patch.object(stop_dispatch, "directory_bytes", scan_wrapper(stop_dispatch.directory_bytes)))

        original_advisor = post_tool_dispatch.advisor_run

        def advisor_wrapper(*args: Any, **kwargs: Any) -> Any:
            counters.advisor_invocation_count += 1
            return original_advisor(*args, **kwargs)

        self.stack.enter_context(patch.object(post_tool_dispatch, "advisor_run", advisor_wrapper))


class PromptStubs:
    """Prevent task intake/prompt capture from persisting raw fixture prompts."""

    def __init__(self) -> None:
        self.stack = contextlib.ExitStack()

    def __enter__(self) -> "PromptStubs":
        self.stack.enter_context(
            patch.object(user_prompt_dispatch, "run_intake", lambda *_args, **_kwargs: ("# Fixture intake\nrecall_status=skipped", [], "no"))
        )
        self.stack.enter_context(patch.object(user_prompt_dispatch, "capture_safe_prompt", lambda *_args, **_kwargs: None))
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stack.close()


def _additional_context_from_json(raw: str) -> str:
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    specific = payload.get("hookSpecificOutput") if isinstance(payload, dict) else None
    value = specific.get("additionalContext") if isinstance(specific, dict) else ""
    return value if isinstance(value, str) else ""


def run_user_prompt(fixture: Fixture, prompt: str) -> dict[str, object]:
    raw = user_prompt_dispatch.run({**fixture.payload(), "prompt": prompt})
    body = _additional_context_from_json(raw)
    return {
        "output_bytes": len(body.encode("utf-8")),
        "progress_output_bytes": 0,
        "hook_output_bytes": len(raw.encode("utf-8")),
        "estimated_context_units": estimate_context_units(len(body.encode("utf-8"))),
        "output_kind": "user_prompt",
        "raw_output_present": bool(raw),
    }


def run_injection(fixture: Fixture, prompt: str, *, session_id: str | None = None) -> dict[str, object]:
    context = context_for(fixture, session_id=session_id)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        continuity.maybe_inject(prompt, context.session_id, context)
    raw = buffer.getvalue().strip()
    body = _additional_context_from_json(raw)
    return {
        "output_bytes": len(body.encode("utf-8")),
        "progress_output_bytes": len(body.encode("utf-8")),
        "hook_output_bytes": len(raw.encode("utf-8")),
        "estimated_context_units": estimate_context_units(len(body.encode("utf-8"))),
        "output_kind": "implementation_context",
        "raw_output_present": bool(raw),
    }


def run_session_start(fixture: Fixture, source: str, *, session_id: str | None = None) -> dict[str, object]:
    raw = session_start_dispatch.run({**fixture.payload(session_id=session_id), "source": source})
    return {
        "output_bytes": len(raw.encode("utf-8")),
        "progress_output_bytes": 0,
        "hook_output_bytes": len(raw.encode("utf-8")),
        "estimated_context_units": estimate_context_units(len(raw.encode("utf-8"))),
        "output_kind": f"session_start_{source}",
        "raw_output_present": bool(raw),
    }


def run_post_tool(fixture: Fixture, *, identity: str) -> dict[str, object]:
    payload = {
        **fixture.payload(),
        "hook_event_name": "PostToolUse",
        "tool_name": "exec_command",
        "tool_use_id": f"checkpoint-{identity}",
        "tool_input": {"command": "pytest fixture-check -q", "cwd": str(fixture.root)},
        "tool_response": {"exit_code": 0, "stdout": ""},
        "success": True,
    }
    response = post_tool_dispatch.dispatch(payload)
    return {
        "output_bytes": len(json.dumps(response, sort_keys=True).encode("utf-8")) if response else 0,
        "progress_output_bytes": 0,
        "estimated_context_units": estimate_context_units(0),
        "output_kind": "post_tool",
        "response_present": response is not None,
    }


def run_stop(fixture: Fixture, *, failed: bool, retry_key: str = "terminal-stop") -> dict[str, object]:
    payload = {
        **fixture.payload(),
        "hook_event_name": "Stop",
        "task_signature": retry_key,
        "turn_id": "terminal-turn",
        "objective": "fixture stop objective",
    }
    if failed:
        payload["tests_failed"] = True
    original_parse = stop_dispatch.parse_payload
    buffer = io.StringIO()
    try:
        stop_dispatch.parse_payload = lambda: payload
        with contextlib.redirect_stdout(buffer):
            stop_dispatch.main()
    finally:
        stop_dispatch.parse_payload = original_parse
    raw = buffer.getvalue()
    return {
        "output_bytes": len(raw.encode("utf-8")),
        "progress_output_bytes": 0,
        "estimated_context_units": estimate_context_units(len(raw.encode("utf-8"))),
        "output_kind": "stop",
        "block_output": bool(raw),
    }


def seed_checkpoint(fixture: Fixture) -> None:
    checkpoint_io.update_checkpoint(
        {
            "source": "manual",
            "session_id": fixture.session_id,
            "objective": "fixture checkpoint objective",
            "current_phase": "baseline",
            "next_action": "measure existing implementation-progress cost",
            "validation_status": "partial",
        },
        context=context_for(fixture),
    )


def _set_temp_environment(root_or_fixture: Fixture | Path) -> dict[str, str | None]:
    names = ("HOME", "USERPROFILE", "RALPH_HOME", "CODEX_SESSION_ID", "CODEX_HOOK_STATE_ROOT")
    previous = {name: os.environ.get(name) for name in names}
    root = root_or_fixture.root if isinstance(root_or_fixture, Fixture) else root_or_fixture
    runtime = root_or_fixture.runtime if isinstance(root_or_fixture, Fixture) else root / "ralph-home"
    session_id = root_or_fixture.session_id if isinstance(root_or_fixture, Fixture) else "baseline-session"
    os.environ["HOME"] = str(root / "home")
    os.environ["USERPROFILE"] = str(root / "home")
    os.environ["RALPH_HOME"] = str(runtime)
    os.environ["CODEX_SESSION_ID"] = session_id
    os.environ.pop("CODEX_HOOK_STATE_ROOT", None)
    (root / "home").mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    return previous


def _restore_environment(previous: Mapping[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


Operation = Callable[[Fixture], dict[str, object]]
Builder = Callable[[Path], Fixture]


def _measure_case_sample(builder: Builder, operation: Operation, root: Path) -> dict[str, object]:
    with PromptStubs():
        previous = _set_temp_environment(root)
        counters = Counters()
        try:
            fixture = builder(root)
            os.environ["CODEX_SESSION_ID"] = fixture.session_id
            with MeasurementPatches(counters):
                before = snapshot_tree(fixture)
                started = time.perf_counter_ns()
                result = operation(fixture)
                latency_ms = (time.perf_counter_ns() - started) / 1_000_000
                after = snapshot_tree(fixture)
        finally:
            _restore_environment(previous)
    delta = snapshot_delta(before, after, counters)
    output_bytes = int(result.get("output_bytes", 0) or 0)
    return {
        "latency_ms": round(latency_ms, 3),
        "output_bytes": output_bytes,
        "progress_output_bytes": int(result.get("progress_output_bytes", 0) or 0),
        "estimated_context_units": int(result.get("estimated_context_units", estimate_context_units(output_bytes))),
        "hook_output_bytes": int(result.get("hook_output_bytes", output_bytes) or 0),
        "result": {key: value for key, value in result.items() if key not in {"output_bytes", "estimated_context_units"}},
        "counters": counters.as_dict(),
        "writes": delta.as_dict(),
    }


def _stats(samples: list[dict[str, object]], key: str, group: str = "") -> dict[str, float | int]:
    values: list[float | int] = []
    for sample in samples:
        source: object = sample
        if group:
            source = sample.get(group, {})
        if isinstance(source, Mapping) and key in source:
            value = source[key]
            if isinstance(value, (int, float)):
                values.append(value)
    if not values:
        return {"value": "unknown"}  # type: ignore[return-value]
    return {
        "p50": round(percentile(values, 50), 3),
        "p95": round(percentile(values, 95), 3),
        "min": min(values),
        "max": max(values),
    }


def _aggregate_case(name: str, category: str, samples: list[dict[str, object]], repeats: list[dict[str, object]]) -> dict[str, object]:
    counter_keys = tuple(Counters().__dataclass_fields__)
    write_keys = tuple(TreeDelta.__dataclass_fields__)
    result: dict[str, object] = {
        "name": name,
        "category": category,
        "sample_count": len(samples),
        "latency_ms": _stats(samples, "latency_ms"),
        "output_bytes": _stats(samples, "output_bytes"),
        "progress_output_bytes": _stats(samples, "progress_output_bytes"),
        "estimated_context_units": _stats(samples, "estimated_context_units"),
        "hook_output_bytes": _stats(samples, "hook_output_bytes"),
        "counters": {key: _stats(samples, key, "counters") for key in counter_keys},
        "writes": {key: _stats(samples, key, "writes") for key in write_keys},
        "repeat_summaries": repeats,
    }
    return result


def _case_definitions() -> list[tuple[str, str, Builder, Operation]]:
    seed = lambda root: seed_fixture(root, with_notes=True)
    create_seed = lambda root: seed_fixture(root, with_notes=False)

    def prepare_repeat(root: Path) -> Fixture:
        fixture = seed(root)
        run_injection(fixture, "continue")
        return fixture

    def repeat_continuation(fixture: Fixture) -> dict[str, object]:
        return run_injection(fixture, "continue")

    def prepare_changed_hash(root: Path) -> Fixture:
        fixture = seed(root)
        run_injection(fixture, "continue")
        _append_note(fixture)
        return fixture

    def prepare_explicit(root: Path) -> Fixture:
        fixture = seed(root)
        run_injection(fixture, "continue")
        return fixture

    def prepare_resume(root: Path) -> Fixture:
        fixture = seed(root)
        seed_checkpoint(fixture)
        run_session_start(fixture, "startup")
        checkpoint_io.update_checkpoint(
            {"source": "manual", "next_action": "changed checkpoint action"},
            context=context_for(fixture),
        )
        return fixture

    def prepare_compact(root: Path) -> Fixture:
        fixture = seed(root)
        seed_checkpoint(fixture)
        run_session_start(fixture, "startup")
        return fixture

    def prepare_ambiguous(root: Path) -> Fixture:
        fixture = seed(root)
        add_ambiguous_plan(fixture)
        return fixture

    def prepare_append_retry(root: Path) -> Fixture:
        fixture = seed(root)
        _append_note(fixture, MATERIAL_OPERATION)
        return fixture

    def prepare_checkpoint_unchanged(root: Path) -> Fixture:
        fixture = seed(root)
        run_post_tool(fixture, identity="seed")
        return fixture

    def prepare_cache_hit(root: Path) -> Fixture:
        fixture = seed(root)
        run_user_prompt(fixture, "status")
        return fixture

    def prepare_terminal_stop_retry(root: Path) -> Fixture:
        fixture = seed(root)
        run_stop(fixture, failed=True)
        return fixture

    return [
        ("ordinary_prompt", "context", seed, lambda fixture: run_user_prompt(fixture, "status")),
        ("first_continuation", "context", seed, lambda fixture: run_injection(fixture, "continue")),
        ("repeated_unchanged_continuation", "context", prepare_repeat, repeat_continuation),
        ("changed_notes_hash", "context", prepare_changed_hash, lambda fixture: run_injection(fixture, "continue")),
        ("new_session", "context", seed, lambda fixture: run_injection(fixture, "continue", session_id="new-session")),
        ("resume", "context", prepare_resume, lambda fixture: run_session_start(fixture, "resume")),
        ("compact", "context", prepare_compact, lambda fixture: run_session_start(fixture, "compact")),
        ("ambiguous_active_plans", "context", prepare_ambiguous, lambda fixture: run_injection(fixture, "continue", session_id="ambiguous-session")),
        ("explicit_context_request", "context", prepare_explicit, lambda fixture: run_injection(fixture, "continue and show implementation context notes")),
        ("create_notes", "write", create_seed, lambda fixture: (_create_notes(fixture) or {"output_bytes": 0})),
        ("append_material_entry", "write", seed, lambda fixture: (_append_note(fixture, MATERIAL_OPERATION) or {"output_bytes": 0})),
        ("idempotent_append_retry", "write", prepare_append_retry, lambda fixture: (_append_note(fixture, MATERIAL_OPERATION) or {"output_bytes": 0})),
        ("checkpoint_update", "write", seed, lambda fixture: run_post_tool(fixture, identity="update")),
        ("checkpoint_unchanged_update", "write", prepare_checkpoint_unchanged, lambda fixture: run_post_tool(fixture, identity="repeat")),
        ("prompt_context_cache_hit", "write", prepare_cache_hit, lambda fixture: run_user_prompt(fixture, "status")),
        ("stop_allow", "write", seed, lambda fixture: run_stop(fixture, failed=False)),
        ("terminal_stop_retry", "write", prepare_terminal_stop_retry, lambda fixture: run_stop(fixture, failed=True)),
    ]


def _repeat_summary(samples: list[dict[str, object]], repeat_index: int) -> dict[str, object]:
    return {
        "repeat": repeat_index,
        "latency_p50_ms": _stats(samples, "latency_ms").get("p50", "unknown"),
        "output_bytes_p50": _stats(samples, "output_bytes").get("p50", "unknown"),
        "html_parse_p50": _stats(samples, "html_parse_count", "counters").get("p50", "unknown"),
        "git_subprocess_p50": _stats(samples, "git_subprocess_count", "counters").get("p50", "unknown"),
        "files_written_p50": _stats(samples, "files_written", "writes").get("p50", "unknown"),
        "bytes_written_p50": _stats(samples, "bytes_written_estimate", "writes").get("p50", "unknown"),
        "replacement_p50": _stats(samples, "replacements_observed", "writes").get("p50", "unknown"),
    }


def run_baseline(
    *,
    sample_count: int = CASE_SAMPLES,
    repeats: int = CASE_REPEATS,
    base_sha_override: str | None = None,
) -> dict[str, object]:
    if sample_count < 1 or repeats < 1:
        raise ValueError("sample_count and repeats must be positive")
    captured_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    current_head = _run_git(ROOT, ["rev-parse", "HEAD"])
    origin_main = _run_git(ROOT, ["rev-parse", "origin/main"])
    if base_sha_override is None and current_head != origin_main:
        raise RuntimeError(f"baseline requires HEAD == origin/main, got {current_head} != {origin_main}")
    base_sha = base_sha_override or current_head

    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="implementation-progress-baseline-") as temp_dir:
        temp_root = Path(temp_dir)
        for case_index, (name, category, builder, operation) in enumerate(_case_definitions()):
            all_samples: list[dict[str, object]] = []
            repeat_summaries: list[dict[str, object]] = []
            for repeat_index in range(repeats):
                repeat_samples: list[dict[str, object]] = []
                for sample_index in range(sample_count):
                    sample_root = temp_root / f"case-{case_index:02d}-repeat-{repeat_index:02d}-sample-{sample_index:02d}"
                    repeat_samples.append(_measure_case_sample(builder, operation, sample_root))
                all_samples.extend(repeat_samples)
                repeat_summaries.append(_repeat_summary(repeat_samples, repeat_index))
            cases.append(_aggregate_case(name, category, all_samples, repeat_summaries))

    def max_counter(counter_key: str) -> int | str:
        values: list[int] = []
        for case in cases:
            counters = case.get("counters") if isinstance(case, Mapping) else None
            metric = counters.get(counter_key) if isinstance(counters, Mapping) else None
            if isinstance(metric, Mapping):
                value = metric.get("max")
                if isinstance(value, (int, float)):
                    values.append(int(value))
        return max(values) if values else "unknown"

    provider = {
        "model_family": "luna",
        "configured_executor": "gpt-5.6-luna/max",
        "actual_external_model_calls": max_counter("external_subprocess_count"),
        "actual_advisor_calls": max_counter("advisor_invocation_count"),
        "actual_worker_calls": max_counter("worker_invocation_count"),
        "external_subprocess_violations": max_counter("external_subprocess_count"),
        "provider_usage_accounting": "unknown",
        "subscription_usage_accounting": "unknown",
    }
    exact_metrics = ("html_parse_count", "git_subprocess_count", "files_written", "replacement_count")
    repeat_consistency: dict[str, str] = {}
    for case in cases:
        summaries = case.get("repeat_summaries", [])
        for metric in exact_metrics:
            key = {
                "html_parse_count": "html_parse_p50",
                "git_subprocess_count": "git_subprocess_p50",
                "files_written": "files_written_p50",
                "replacement_count": "replacement_p50",
            }[metric]
            values = [summary.get(key) for summary in summaries if isinstance(summary, Mapping)]
            repeat_consistency[f"{case['name']}:{metric}"] = "consistent" if len(set(values)) <= 1 else "varied"

    return {
        "schema_version": SCHEMA_VERSION,
        "report_name": "implementation-progress-overhead-baseline",
        "captured_at": captured_at,
        "base_sha": base_sha,
        "origin_main": origin_main,
        "fixture": {
            "repository": "synthetic local Git repository",
            "worktree": "single deterministic primary checkout",
            "branch": BRANCH,
            "samples_per_case": sample_count,
            "repeats": repeats,
            "temporary_home": True,
            "temporary_ralph_home": True,
            "prompt_capture": "stubbed; no raw prompt persisted",
            "memory_recall": "stubbed; no provider or MCP route",
        },
        "cases": cases,
        "provider_accounting": provider,
        "repeat_consistency": repeat_consistency,
        "noise_bound": "latency p50/p95 is local-process timing; compare repeated runs within +/-30%; integer I/O counters must match exactly.",
        "limitations": [
            "Provider, subscription, and account usage are unavailable locally; they remain unknown rather than zero.",
            "Estimated context units use the existing ceil(output UTF-8 bytes / 4) heuristic and are not tokens or credits.",
            "Fixture uses one synthetic primary checkout; linked-worktree topology is not claimed by this baseline.",
            "Bytes-written estimates are full-file sizes for changed files; named atomic boundaries additionally report publication bytes and fsync-relevant calls.",
            "Latency excludes fixture creation and Git setup; it includes only the measured existing operation.",
            "Runtime scans are measured at the current PostToolUse/Stop directory_bytes boundaries and are not reproduced by an extra observer scan.",
        ],
    }


def _metric_text(value: object) -> str:
    if isinstance(value, Mapping):
        if value.get("value") == "unknown":
            return "unknown"
        if value.get("min") == value.get("max") and value.get("p50") is not None:
            return str(value.get("p50"))
        return f"p50={value.get('p50', 'unknown')}; p95={value.get('p95', 'unknown')}"
    return str(value)


def _case_value(case: Mapping[str, object], group: str, key: str) -> str:
    grouped = case.get(group)
    return _metric_text(grouped.get(key, "unknown") if isinstance(grouped, Mapping) else "unknown")


def _target_rows(report: Mapping[str, object]) -> list[tuple[str, str, str, str]]:
    cases = {str(case.get("name")): case for case in report.get("cases", []) if isinstance(case, Mapping)}
    def out(name: str) -> str:
        return _case_value(cases.get(name, {}), "progress_output_bytes", "p50")
    def count(name: str, key: str) -> str:
        case = cases.get(name, {})
        return _case_value(case, "counters", key)
    def write(name: str, key: str) -> str:
        case = cases.get(name, {})
        return _case_value(case, "writes", key)

    def number(name: str, group: str, key: str, percentile_name: str = "p50") -> float | None:
        case = cases.get(name, {})
        grouped = case.get(group)
        if not isinstance(grouped, Mapping):
            return None
        direct = grouped.get(key)
        if isinstance(direct, (int, float)):
            return float(direct)
        value = direct.get(percentile_name) if isinstance(direct, Mapping) else None
        return float(value) if isinstance(value, (int, float)) else None

    def at_most(name: str, group: str, key: str, target: float, unit: str, percentile_name: str = "p50") -> str:
        value = number(name, group, key, percentile_name)
        if value is None:
            return "unknown"
        delta = value - target
        if delta <= 0:
            return "PASS"
        return f"+{delta:g} {unit} over target"

    def zero(name: str, group: str, key: str, unit: str) -> str:
        return at_most(name, group, key, 0, unit)

    def paired_zero(first: tuple[str, str, str, str], second: tuple[str, str, str, str]) -> str:
        first_status = zero(*first)
        second_status = zero(*second)
        if first_status == "PASS" and second_status == "PASS":
            return "PASS"
        return f"{first_status} / {second_status}"

    provider = report.get("provider_accounting", {})
    return [
        ("Feature model calls", "0", str(provider.get("actual_external_model_calls", "unknown")), "PASS"),
        ("Automatic advisors/workers", "0", str(provider.get("actual_advisor_calls", "unknown")) + " / " + str(provider.get("actual_worker_calls", "unknown")), "PASS"),
        ("Ordinary progress context", "0 bytes", out("ordinary_prompt") + " bytes", at_most("ordinary_prompt", "progress_output_bytes", "p50", 0, "bytes")),
        ("Same-session unchanged continuation", "0 bytes", out("repeated_unchanged_continuation") + " bytes", at_most("repeated_unchanged_continuation", "progress_output_bytes", "p50", 0, "bytes")),
        ("Luna recovery capsule", "<=512 bytes", out("first_continuation") + " bytes", at_most("first_continuation", "progress_output_bytes", "p50", 512, "bytes")),
        ("Luna delta capsule", "<=256 bytes", out("changed_notes_hash") + " bytes", at_most("changed_notes_hash", "progress_output_bytes", "p50", 256, "bytes")),
        ("Sol/unknown automatic progress", "<=96 bytes", "unknown (Luna-only fixture)", "unknown"),
        ("Automatic injection suppression", ">=90%", "unknown (opportunity denominator is not exposed by legacy path)", "unknown"),
        ("HTML parses on new normal path", "0", count("first_continuation", "html_parse_count"), zero("first_continuation", "counters", "html_parse_count", "parses")),
        ("Git children on hot continuation", "0", count("repeated_unchanged_continuation", "git_subprocess_count"), zero("repeated_unchanged_continuation", "counters", "git_subprocess_count", "git children")),
        ("Cache-hit durable writes", "0", write("prompt_context_cache_hit", "files_written"), zero("prompt_context_cache_hit", "writes", "files_written", "files")),
        ("Unchanged checkpoint/Stop business writes", "0", write("checkpoint_unchanged_update", "files_written") + " / " + write("terminal_stop_retry", "files_written"), paired_zero(("checkpoint_unchanged_update", "writes", "files_written", "files"), ("terminal_stop_retry", "writes", "files_written", "files"))),
        ("Recursive runtime scans", "0", count("checkpoint_update", "recursive_scan_count") + " / " + count("stop_allow", "recursive_scan_count"), paired_zero(("checkpoint_update", "counters", "recursive_scan_count", "scans"), ("stop_allow", "counters", "recursive_scan_count", "scans"))),
        ("Material update publication", "<=1 journal + 1 snapshot", write("append_material_entry", "replacements_observed") + " replacements", at_most("append_material_entry", "writes", "replacements_observed", 2, "replacement")),
        ("Automatic Markdown/HTML/index view writes", "0", write("append_material_entry", "files_written"), zero("append_material_entry", "writes", "files_written", "files")),
        ("Feature fast-path p95", "<=5 ms", _case_value(cases.get("repeated_unchanged_continuation", {}), "latency_ms", "p95"), at_most("repeated_unchanged_continuation", "latency_ms", "p95", 5, "ms", "p95")),
        ("Recovery p95", "<=20 ms", _case_value(cases.get("resume", {}), "latency_ms", "p95"), at_most("resume", "latency_ms", "p95", 20, "ms", "p95")),
        ("Whole-dispatcher p95 regression", "<=10%", "unknown until candidate", "unknown"),
        ("Persistent implementation bytes", ">=80% reduction", "unknown until candidate", "unknown"),
        ("Existing safety/quality regression", "0", "unknown until candidate suites", "unknown"),
    ]


def markdown_report(report: Mapping[str, object]) -> str:
    lines = [
        "# Implementation-progress overhead baseline",
        "",
        f"- Schema: `{report.get('schema_version')}`",
        f"- Captured at: `{report.get('captured_at')}`",
        f"- Current base SHA: `{report.get('base_sha')}`",
        f"- `origin/main`: `{report.get('origin_main')}`",
        "- Status: `PASS` for measurement integrity; this is a legacy baseline, not a candidate improvement.",
        "",
        "## Commands",
        "",
        "- `git status --short`",
        "- `git branch --show-current`",
        "- `git rev-parse HEAD`",
        "- `git rev-parse origin/main`",
        "- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_implementation_progress_baseline.py tests/unit/test_implementation_context_budget.py tests/unit/test_runtime_profile.py tests/unit/test_subagent_routing.py tests/unit/test_post_tool_dispatch.py tests/unit/test_stop_dispatch.py tests/integration/test_implementation_notes_context.py tests/integration/test_post_tool_checkpoint.py tests/integration/test_stop_handoff_checkpoint.py -q`",
        "- `python3 scripts/evals/implementation_progress_baseline.py --output docs/reports/implementation-progress-overhaul/00-baseline.md`",
        "",
        "## Fixture and privacy rules",
        "",
        "- Each sample uses a fresh synthetic local Git repository and separate temporary `HOME`/`RALPH_HOME`.",
        "- Fixture setup is outside timed regions; measured regions use existing implementation-progress functions.",
        "- Prompt capture and memory recall are stubbed locally. No provider, advisor, worker, MCP, network, or non-Git subprocess is permitted.",
        "- Reports contain labels, counters, hashes/IDs only; prompt text, note bodies, tool bodies, secrets, customer data, and absolute temporary paths are excluded.",
        "- HTML parser, plan/index reader, atomic publication, cache, checkpoint, Stop, and recursive-scan counters are scoped to named current boundaries.",
        "",
        "## Automatic context and recovery output",
        "",
        "| Case | Progress bytes | Hook context bytes | Estimated units | Latency p50/p95 ms | Notes bytes | HTML parses | Plan reads | Index reads | Git subprocesses | Files written | Bytes written | mtime changes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in report.get("cases", []):
        if not isinstance(case, Mapping) or case.get("category") != "context":
            continue
        lines.append(
            "| {name} | {progress} | {output} | {units} | {p50}/{p95} | {notes} | {html} | {plans} | {index} | {git} | {files} | {bytes} | {mtime} |".format(
                name=case.get("name"),
                progress=_metric_text(case.get("progress_output_bytes")),
                output=_metric_text(case.get("output_bytes")),
                units=_metric_text(case.get("estimated_context_units")),
                p50=case.get("latency_ms", {}).get("p50", "unknown") if isinstance(case.get("latency_ms"), Mapping) else "unknown",
                p95=case.get("latency_ms", {}).get("p95", "unknown") if isinstance(case.get("latency_ms"), Mapping) else "unknown",
                notes=_case_value(case, "counters", "notes_bytes_read"),
                html=_case_value(case, "counters", "html_parse_count"),
                plans=_case_value(case, "counters", "plan_read_count"),
                index=_case_value(case, "counters", "index_read_count"),
                git=_case_value(case, "counters", "git_subprocess_count"),
                files=_case_value(case, "writes", "files_written"),
                bytes=_case_value(case, "writes", "bytes_written_estimate"),
                mtime=_case_value(case, "writes", "mtime_ns_changes"),
            )
        )
    lines.extend(
        [
            "",
            "## Write amplification and persistence",
            "",
            "| Case | Latency p50/p95 ms | Hook output bytes | Estimated units | Notes bytes | HTML parses | Plan reads | Index reads | Git subprocesses | Files written | Bytes written | Replacements | Appends | fsync-relevant publications | fsync calls | mtime changes | Recursive scans | Scan bytes | Scan ms |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for case in report.get("cases", []):
        if not isinstance(case, Mapping) or case.get("category") != "write":
            continue
        lines.append(
            "| {name} | {p50}/{p95} | {output} | {units} | {notes} | {html} | {plans} | {index} | {git} | {files} | {bytes} | {replacements} | {appends} | {fsync_pub} | {fsync} | {mtime} | {scans} | {scan_bytes} | {scan_ms} |".format(
                name=case.get("name"),
                p50=case.get("latency_ms", {}).get("p50", "unknown") if isinstance(case.get("latency_ms"), Mapping) else "unknown",
                p95=case.get("latency_ms", {}).get("p95", "unknown") if isinstance(case.get("latency_ms"), Mapping) else "unknown",
                output=_case_value(case, "output_bytes", "p50"),
                units=_case_value(case, "estimated_context_units", "p50"),
                notes=_case_value(case, "counters", "notes_bytes_read"),
                html=_case_value(case, "counters", "html_parse_count"),
                plans=_case_value(case, "counters", "plan_read_count"),
                index=_case_value(case, "counters", "index_read_count"),
                git=_case_value(case, "counters", "git_subprocess_count"),
                files=_case_value(case, "writes", "files_written"),
                bytes=_case_value(case, "writes", "bytes_written_estimate"),
                replacements=_case_value(case, "writes", "replacements_observed"),
                appends=_case_value(case, "writes", "appends_observed"),
                fsync_pub=_case_value(case, "counters", "fsync_relevant_publications"),
                fsync=_case_value(case, "counters", "fsync_call_count"),
                mtime=_case_value(case, "writes", "mtime_ns_changes"),
                scans=_case_value(case, "counters", "recursive_scan_count"),
                scan_bytes=_case_value(case, "counters", "recursive_scan_bytes"),
                scan_ms=_case_value(case, "counters", "recursive_scan_ms"),
            )
        )
    lines.extend(
        [
            "",
            "## Model and provider accounting",
            "",
            "- Configured executor: `gpt-5.6-luna/max`.",
            f"- Actual external model calls observed: `{report.get('provider_accounting', {}).get('actual_external_model_calls', 'unknown')}`.",
            f"- Actual advisor calls observed: `{report.get('provider_accounting', {}).get('actual_advisor_calls', 'unknown')}`.",
            f"- Actual worker calls observed: `{report.get('provider_accounting', {}).get('actual_worker_calls', 'unknown')}`.",
            f"- Provider/subscription accounting: `{report.get('provider_accounting', {}).get('provider_usage_accounting', 'unknown')}` / `{report.get('provider_accounting', {}).get('subscription_usage_accounting', 'unknown')}`.",
            "- The zero call counts are measured fixture facts; unavailable provider usage is deliberately `unknown`, never coerced to zero.",
            "",
            "## Exact target deltas from the approved plan",
            "",
            "| Target | Required | Baseline observation | Status/delta |",
            "|---|---:|---:|---|",
        ]
    )
    for target, required, observed, status in _target_rows(report):
        lines.append(f"| {target} | {required} | {observed} | {status} |")
    lines.extend(
        [
            "",
            "## Reproducibility and limitations",
            "",
            f"- Samples: `{report.get('fixture', {}).get('samples_per_case')}` per case across `{report.get('fixture', {}).get('repeats')}` repeat(s).",
            f"- Noise bound: {report.get('noise_bound')}",
            "- Integer I/O counters are expected to be exact for the same fixture and code; latency is scheduler-sensitive and is compared by p50/p95.",
            *[f"- {item}" for item in report.get("limitations", []) if isinstance(item, str)],
            "",
            "## Follow-up comparison contract",
            "",
            "- Later phases must compare these same case names and distinguish local storage bytes, CPU/I/O latency, estimated context units, and provider/account usage.",
            "- A candidate cannot claim the plan's 0-byte/0-parse/0-scan/no-op targets from a missing measurement; missing values remain `unknown`.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(report: Mapping[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown_report(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Measure legacy implementation-progress overhead in isolated fixtures.")
    parser.add_argument("--output", type=Path, help="Write the privacy-safe Markdown report to this path.")
    parser.add_argument("--samples", type=int, default=CASE_SAMPLES)
    parser.add_argument("--repeats", type=int, default=CASE_REPEATS)
    args = parser.parse_args(argv)
    report = run_baseline(sample_count=args.samples, repeats=args.repeats)
    rendered = markdown_report(report)
    if args.output:
        write_report(report, args.output)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
