from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

import fcntl

from implementation_notes_lib import (
    ImplementationNotesError,
    append_entry,
    ensure_not_red,
    git_common_dir_for,
    now_local,
    resolve_for_write,
    run_git,
    valid_non_initial_entries,
)

INDEX_JSON_NAME = "implementation-index.json"
INDEX_MD_NAME = "implementation-index.md"
INDEX_LOCK_NAME = "implementation-index.lock"
INDEX_VERSION = 2
EVENTS_LIMIT = 2_000
ALLOWED_EVENTS = {
    "notes_created",
    "note_appended",
    "guard_validated",
    "implemented",
    "plan_updated",
    "loose_commit_recorded",
    "index_updated",
    "consolidated",
}


def _rel(path: Path, root: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(resolved)


def index_json_path(primary_root: Path) -> Path:
    return resolve_for_write(primary_root / ".ralph" / "plans" / INDEX_JSON_NAME, primary_root)


def index_md_path(primary_root: Path) -> Path:
    return resolve_for_write(primary_root / ".ralph" / "plans" / INDEX_MD_NAME, primary_root)


def index_lock_path(primary_root: Path) -> Path:
    return resolve_for_write(primary_root / ".ralph" / "plans" / INDEX_LOCK_NAME, primary_root)


@contextlib.contextmanager
def index_lock(primary_root: Path):
    """Serialize index transactions across hook/process writers."""
    path = primary_root / ".ralph" / "plans" / INDEX_LOCK_NAME
    # Validate the lexical location before opening it. The final component is
    # then opened with O_NOFOLLOW so a lock symlink cannot redirect the
    # exclusion to the index or to another file, while parent links that stay
    # inside the allowed plans root remain supported.
    resolve_for_write(path, primary_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ImplementationNotesError(f"implementation index lock cannot be a symlink: {path}")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags, 0o600)
        lock_stat = os.fstat(descriptor)
        if lock_stat.st_nlink != 1:
            raise ImplementationNotesError(f"implementation index lock must not be hard-linked: {path}")
        index_path = primary_root / ".ralph" / "plans" / INDEX_JSON_NAME
        if index_path.exists() and os.path.samefile(path, index_path):
            raise ImplementationNotesError(f"implementation index lock must not alias the index: {path}")
        with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
            descriptor = -1
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise ImplementationNotesError(f"could not open implementation index lock: {path}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _atomic_write(path: Path, text: str) -> None:
    """Write an already-validated artifact without exposing partial JSON/MD."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            if existing_mode is not None:
                os.fchmod(handle.fileno(), existing_mode)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        temporary = ""
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def current_git_metadata(root: Path) -> dict[str, str]:
    return {
        "branch": run_git(root, "branch", "--show-current") or run_git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "commit": run_git(root, "rev-parse", "HEAD"),
    }


def empty_index(primary_root: Path) -> dict[str, Any]:
    return {
        "version": INDEX_VERSION,
        "canonical_repo_root": str(primary_root.resolve()),
        "updated_at": now_local(),
        "plans": [],
        "loose_commits": [],
        "events": [],
    }


def _quarantine_corrupt_index(path: Path) -> Path:
    """Move an unreadable index aside without deleting the user's evidence."""
    for suffix in range(100):
        candidate = path.with_name(f"{path.name}.corrupt-{os.getpid()}-{suffix}")
        if not candidate.exists():
            os.replace(path, candidate)
            return candidate
    raise ImplementationNotesError(f"could not quarantine corrupt implementation index: {path}")


def _index_shape_is_valid(data: dict[str, Any]) -> bool:
    """Validate the nested shapes consumed by mutation and Markdown rendering."""
    for key in ("plans", "loose_commits", "events"):
        values = data.get(key)
        if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
            return False
    for plan in data["plans"]:
        commits = plan.get("commits", [])
        if not isinstance(commits, list):
            return False
    return True


def _load_index_unlocked(primary_root: Path, *, quarantine_corrupt: bool = True) -> dict[str, Any]:
    path = index_json_path(primary_root)
    if not path.exists():
        return empty_index(primary_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        if quarantine_corrupt:
            _quarantine_corrupt_index(path)
        return empty_index(primary_root)
    if not isinstance(data, dict):
        if quarantine_corrupt:
            _quarantine_corrupt_index(path)
        return empty_index(primary_root)
    version = data.get("version", 1)
    # Never silently reinterpret a newer schema as the current one. A future
    # writer may have changed nested semantics that this reader cannot safely
    # preserve, so fail closed and leave the source intact for an explicit
    # migration.
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        if quarantine_corrupt:
            _quarantine_corrupt_index(path)
        return empty_index(primary_root)
    if version > INDEX_VERSION:
        raise ImplementationNotesError(
            f"implementation index schema version {version} is newer than supported version {INDEX_VERSION}"
        )
    data["version"] = version
    data["canonical_repo_root"] = str(primary_root.resolve())
    data.setdefault("plans", [])
    data.setdefault("loose_commits", [])
    data.setdefault("events", [])
    if not _index_shape_is_valid(data):
        if quarantine_corrupt:
            _quarantine_corrupt_index(path)
        return empty_index(primary_root)
    return data


def load_index(primary_root: Path, *, quarantine_corrupt: bool = True) -> dict[str, Any]:
    """Read the index under the same lock used by recovery and writers."""
    # A read of a repository that has never created an implementation index is
    # side-effect free. Writers still take the lock once an index exists (or
    # when they create one), while context readers do not need to create a
    # plans directory/lock just to return the empty shape.
    if not index_json_path(primary_root).exists():
        return empty_index(primary_root)
    if not quarantine_corrupt:
        # Consolidator dry-run is explicitly report-only: take a best-effort
        # snapshot without creating a lock or quarantining the source file.
        return _load_index_unlocked(primary_root, quarantine_corrupt=False)
    with index_lock(primary_root):
        return _load_index_unlocked(primary_root, quarantine_corrupt=quarantine_corrupt)


def _add_unique(values: list[str], value: str) -> list[str]:
    if value and value not in values:
        values.append(value)
    return values


def _md_cell(value: object) -> str:
    return str(value or "").replace("\n", " ").replace("|", "\\|")


def workspace_instance_id(active_root: Path) -> str:
    return hashlib.sha256(str(active_root.resolve()).encode("utf-8")).hexdigest()[:16]


def latest_entry_metadata(notes_path: Path) -> dict[str, str]:
    try:
        entries = valid_non_initial_entries(notes_path.read_text(encoding="utf-8"))
    except (ImplementationNotesError, OSError):
        return {}
    if not entries:
        return {}
    # The document order is the authoritative tie-breaker. Timestamps are
    # intentionally second-resolution display metadata, not event identity.
    entry = entries[-1]
    category = entry.category
    timestamp = entry.fields.get("Timestamp", "")
    decision = entry.fields.get("Decision", "")
    status = entry.fields.get("Status", "")
    operation_id = entry.fields.get("Operation ID", "")
    material = f"{category}\n{timestamp}\n{decision}\n{status}\n{operation_id}"
    metadata = {
        "latest_entry_hash": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "latest_entry_category": category,
        "latest_entry_at": timestamp,
    }
    if operation_id:
        metadata["latest_entry_operation_id"] = operation_id
    return metadata


def _event_id(event: dict[str, Any]) -> str:
    material = {key: value for key, value in event.items() if key not in {"event_id", "created_at", "timestamp"}}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def append_event(
    data: dict[str, Any],
    *,
    event: str,
    primary_root: Path,
    active_root: Path,
    plan_path: Path | None = None,
    notes_path: Path | None = None,
    status: str = "",
    commit: str = "",
    branch: str = "",
    session_id: str = "",
    operation_id: str = "",
) -> dict[str, Any]:
    if event not in ALLOWED_EVENTS:
        raise ImplementationNotesError(f"unknown implementation index event: {event}")
    git_meta = current_git_metadata(active_root)
    latest_notes = latest_entry_metadata(notes_path) if notes_path and notes_path.exists() else {}
    payload: dict[str, Any] = {
        "event": event,
        "plan": _rel(plan_path, primary_root) if plan_path else "",
        "notes": _rel(notes_path, primary_root) if notes_path else "",
        "status": status,
        "branch": branch or git_meta["branch"],
        "commit": commit or git_meta["commit"],
        "session_id": session_id,
        "active_worktree_root": str(active_root.resolve()),
        "canonical_repo_root": str(primary_root.resolve()),
        "git_common_dir": str(git_common_dir_for(active_root)),
        "workspace_instance_id": workspace_instance_id(active_root),
        "notes_entry_hash": latest_notes.get("latest_entry_hash", ""),
        "operation_id": operation_id,
    }
    ensure_not_red("implementation index event", json.dumps(payload, sort_keys=True))
    event_id = _event_id(payload)
    payload["event_id"] = event_id
    payload["created_at"] = now_local()
    payload["timestamp"] = payload["created_at"]
    events = data.setdefault("events", [])
    if not isinstance(events, list):
        raise ImplementationNotesError("implementation index events must be a list")
    if event == "note_appended" and operation_id:
        # Operation IDs are idempotency keys scoped to one plan/notes resource.
        # The HTML append path rejects a same-target ID with a different
        # payload; a replay of the same lifecycle operation must not create a
        # second durable event.
        existing = next(
            (
                item
                for item in events
                if isinstance(item, dict)
                and item.get("event") == "note_appended"
                and item.get("operation_id") == operation_id
                and item.get("plan") == payload["plan"]
                and item.get("notes") == payload["notes"]
            ),
            None,
        )
        if existing is not None:
            return existing
    if not any(isinstance(item, dict) and item.get("event_id") == event_id for item in events):
        events.append(payload)
        if len(events) > EVENTS_LIMIT:
            del events[:-EVENTS_LIMIT]
    return payload


def _write_index_unlocked(primary_root: Path, data: dict[str, Any]) -> None:
    data["version"] = INDEX_VERSION
    data["canonical_repo_root"] = str(primary_root.resolve())
    data["updated_at"] = now_local()
    rendered_json = json.dumps(data, indent=2, sort_keys=True) + "\n"
    rendered_md = render_markdown(data)
    ensure_not_red("implementation index JSON", rendered_json)
    ensure_not_red("implementation index Markdown", rendered_md)
    _atomic_write(index_json_path(primary_root), rendered_json)
    _atomic_write(index_md_path(primary_root), rendered_md)


def update_index(primary_root: Path, updater) -> Any:
    """Run one read-modify-write transaction under the index lock."""
    with index_lock(primary_root):
        data = _load_index_unlocked(primary_root)
        result = updater(data)
        _write_index_unlocked(primary_root, data)
        return result


def upsert_plan_entry(
    *,
    primary_root: Path,
    plan_path: Path,
    notes_path: Path,
    status: str,
    active_root: Path,
    commit: str = "",
    branch: str = "",
    pr: str = "",
    session_id: str = "",
    event: str = "",
) -> dict[str, Any]:
    with index_lock(primary_root):
        data = _load_index_unlocked(primary_root)
        timestamp = now_local()
        plan_rel = _rel(plan_path, primary_root)
        notes_rel = _rel(notes_path, primary_root)
        git_meta = current_git_metadata(active_root)
        branch = branch or git_meta["branch"]
        commit = commit or ""

        entry = next((item for item in data["plans"] if isinstance(item, dict) and item.get("plan") == plan_rel), None)
        created = entry is None
        if entry is None:
            entry = {
                "type": "plan",
                "plan": plan_rel,
                "notes": notes_rel,
                "status": status,
                "branch": branch,
                "commits": [],
                "pr": pr,
                "session_id": session_id,
                "created_at": timestamp,
                "updated_at": timestamp,
                "workspace_instance_id": workspace_instance_id(active_root),
            }
            data["plans"].append(entry)
        else:
            entry["notes"] = notes_rel
            entry["status"] = status or entry.get("status", "")
            entry["branch"] = branch or entry.get("branch", "")
            entry["pr"] = pr or entry.get("pr", "")
            entry["session_id"] = session_id or entry.get("session_id", "")
            entry["updated_at"] = timestamp
            entry["workspace_instance_id"] = workspace_instance_id(active_root)
            entry.setdefault("commits", [])

        if commit:
            entry["commits"] = _add_unique([str(value) for value in entry.get("commits", [])], commit)
        latest = git_meta["commit"]
        if latest:
            entry["latest_git_sha"] = latest
        entry.update(latest_entry_metadata(notes_path))
        _record_unseen_note_events(
            data,
            primary_root=primary_root,
            active_root=active_root,
            plan_path=plan_path,
            notes_path=notes_path,
            status=entry.get("status", ""),
            commit=commit or latest,
            branch=branch,
            session_id=session_id or entry.get("session_id", ""),
        )
        event_name = event or ("notes_created" if created and status == "active" else "implemented" if status == "implemented" else "plan_updated")
        append_event(
            data,
            event=event_name,
            primary_root=primary_root,
            active_root=active_root,
            plan_path=plan_path,
            notes_path=notes_path,
            status=entry.get("status", ""),
            commit=commit or latest,
            branch=branch,
            session_id=session_id or entry.get("session_id", ""),
        )
        _write_index_unlocked(primary_root, data)
        return entry


def _refresh_notes_metadata_unlocked(
    data: dict[str, Any],
    *,
    primary_root: Path,
    notes_path: Path,
    active_root: Path,
    session_id: str = "",
    branch: str = "",
    commit: str = "",
    operation_id: str = "",
) -> dict[str, Any] | None:
    notes_rel = _rel(notes_path, primary_root)
    entry = next((item for item in data["plans"] if isinstance(item, dict) and item.get("notes") == notes_rel), None)
    if entry is None:
        return None
    git_meta = current_git_metadata(active_root)
    current_branch = branch or git_meta["branch"]
    current_commit = commit or git_meta["commit"]
    if current_branch:
        entry["branch"] = current_branch
    if session_id:
        entry["session_id"] = session_id
    entry["workspace_instance_id"] = workspace_instance_id(active_root)
    entry["updated_at"] = now_local()
    entry.update(latest_entry_metadata(notes_path))
    operation_id = operation_id or str(entry.get("latest_entry_operation_id", ""))
    append_event(
        data,
        event="note_appended",
        primary_root=primary_root,
        active_root=active_root,
        plan_path=primary_root / str(entry.get("plan", "")),
        notes_path=notes_path,
        status=entry.get("status", ""),
        commit=current_commit,
        branch=current_branch,
        session_id=session_id or "unknown",
        operation_id=operation_id,
    )
    return entry


def refresh_notes_metadata(
    *,
    primary_root: Path,
    notes_path: Path,
    active_root: Path,
    session_id: str = "",
    branch: str = "",
    commit: str = "",
    operation_id: str = "",
) -> dict[str, Any] | None:
    with index_lock(primary_root):
        data = _load_index_unlocked(primary_root)
        entry = _refresh_notes_metadata_unlocked(
            data,
            primary_root=primary_root,
            notes_path=notes_path,
            active_root=active_root,
            session_id=session_id,
            branch=branch,
            commit=commit,
            operation_id=operation_id,
        )
        if entry is not None:
            _write_index_unlocked(primary_root, data)
        return entry


def append_note_and_refresh(
    *,
    primary_root: Path,
    notes_path: Path,
    entry_html_text: str,
    category: str,
    active_root: Path,
    session_id: str = "",
    branch: str = "",
    commit: str = "",
    operation_id: str = "",
) -> dict[str, Any] | None:
    """Append a note and index its event under one lifecycle lock.

    The HTML write is idempotent by operation ID. If a process terminates
    after the note replacement but before the index replacement, a later
    lifecycle operation can record the still-visible operation exactly once.
    """
    with index_lock(primary_root):
        data = _load_index_unlocked(primary_root)
        append_entry(notes_path, entry_html_text, category)
        result = _refresh_notes_metadata_unlocked(
            data,
            primary_root=primary_root,
            notes_path=notes_path,
            active_root=active_root,
            session_id=session_id,
            branch=branch,
            commit=commit,
            operation_id=operation_id,
        )
        if result is None:
            # Preserve the legacy standalone append contract: a valid notes
            # document may be appended before its plan is registered. The
            # next plan lifecycle transaction will reconcile its operation ID.
            return None
        _write_index_unlocked(primary_root, data)
        return result


def _record_unseen_note_events(
    data: dict[str, Any],
    *,
    primary_root: Path,
    active_root: Path,
    plan_path: Path,
    notes_path: Path,
    status: str,
    commit: str,
    branch: str,
    session_id: str,
) -> None:
    """Reconcile note IDs visible in HTML but missing from the event log."""
    try:
        note_entries = valid_non_initial_entries(notes_path.read_text(encoding="utf-8"))
    except (ImplementationNotesError, OSError):
        return
    known = {
        (str(item.get("notes", "")), str(item.get("operation_id", "")))
        for item in data.get("events", [])
        if isinstance(item, dict) and item.get("event") == "note_appended"
    }
    for note_entry in note_entries:
        operation_id = note_entry.fields.get("Operation ID", "")
        event_key = (_rel(notes_path, primary_root), operation_id)
        if not operation_id or event_key in known:
            continue
        append_event(
            data,
            event="note_appended",
            primary_root=primary_root,
            active_root=active_root,
            plan_path=plan_path,
            notes_path=notes_path,
            status=status,
            commit=commit,
            branch=branch,
            session_id=session_id or "unknown",
            operation_id=operation_id,
        )
        known.add(event_key)


def record_loose_commit(
    *,
    primary_root: Path,
    commit: str,
    active_root: Path,
    reason: str,
    branch: str = "",
    notes: str = "",
) -> dict[str, Any]:
    if not commit.strip():
        raise ImplementationNotesError("loose commit is required")
    ensure_not_red("loose commit index entry", f"{commit}\n{reason}\n{branch}\n{notes}")
    with index_lock(primary_root):
        data = _load_index_unlocked(primary_root)
        timestamp = now_local()
        git_meta = current_git_metadata(active_root)
        branch = branch or git_meta["branch"]
        entry = next((item for item in data["loose_commits"] if isinstance(item, dict) and item.get("commit") == commit), None)
        if entry is None:
            entry = {
                "type": "loose_commit",
                "commit": commit,
                "branch": branch,
                "reason": reason,
                "notes": notes,
                "linked_plan": None,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            data["loose_commits"].append(entry)
        else:
            entry["branch"] = branch or entry.get("branch", "")
            entry["reason"] = reason or entry.get("reason", "")
            entry["notes"] = notes or entry.get("notes", "")
            entry["updated_at"] = timestamp
        append_event(
            data,
            event="loose_commit_recorded",
            primary_root=primary_root,
            active_root=active_root,
            status="loose_commit",
            commit=commit,
            branch=branch,
        )
        _write_index_unlocked(primary_root, data)
        return entry


def write_index(primary_root: Path, data: dict[str, Any]) -> None:
    with index_lock(primary_root):
        _write_index_unlocked(primary_root, data)


def render_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Implementation Index",
        "",
        f"Canonical repo root: `{data.get('canonical_repo_root', '')}`",
        f"Updated at: `{data.get('updated_at', '')}`",
        "",
        "## Plans",
        "",
        "| Status | Plan | Notes | Branch | Commits | PR | Updated |",
        "|---|---|---|---|---|---|---|",
    ]
    plans = [item for item in data.get("plans", []) if isinstance(item, dict)]
    if plans:
        for item in plans:
            commits = ", ".join(f"`{value}`" for value in item.get("commits", []) if value) or "n/a"
            pr = item.get("pr") or "n/a"
            lines.append(
                "| {status} | [{plan}]({plan}) | [{notes}]({notes}) | `{branch}` | {commits} | {pr} | `{updated}` |".format(
                    status=item.get("status", ""),
                    plan=_md_cell(item.get("plan", "")),
                    notes=_md_cell(item.get("notes", "")),
                    branch=_md_cell(item.get("branch", "")),
                    commits=commits,
                    pr=_md_cell(pr),
                    updated=item.get("updated_at", ""),
                )
            )
    else:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a |")

    lines.extend(
        [
            "",
            "## Implementation Events",
            "",
            "| Event | Plan | Session | Branch | Commit | Worktree | Created |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    events = [item for item in data.get("events", []) if isinstance(item, dict)]
    if events:
        for item in events:
            lines.append(
                "| `{event}` | {plan} | `{session}` | `{branch}` | `{commit}` | `{worktree}` | `{created}` |".format(
                    event=_md_cell(item.get("event", "")),
                    plan=_md_cell(item.get("plan", "")),
                    session=_md_cell(item.get("session_id", "")),
                    branch=_md_cell(item.get("branch", "")),
                    commit=_md_cell(item.get("commit", "")),
                    worktree=_md_cell(item.get("workspace_instance_id", "")),
                    created=_md_cell(item.get("created_at", "")),
                )
            )
    else:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a |")

    lines.extend(
        [
            "",
            "## Loose Commits",
            "",
            "| Commit | Branch | Reason | Notes | Updated |",
            "|---|---|---|---|---|",
        ]
    )
    loose = [item for item in data.get("loose_commits", []) if isinstance(item, dict)]
    if loose:
        for item in loose:
            lines.append(
                "| `{commit}` | `{branch}` | {reason} | {notes} | `{updated}` |".format(
                    commit=_md_cell(item.get("commit", "")),
                    branch=_md_cell(item.get("branch", "")),
                    reason=_md_cell(item.get("reason", "")),
                    notes=_md_cell(item.get("notes", "")),
                    updated=item.get("updated_at", ""),
                )
            )
    else:
        lines.append("| n/a | n/a | n/a | n/a | n/a |")
    return "\n".join(lines) + "\n"
