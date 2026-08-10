#!/usr/bin/env python3
"""Public deterministic CLI for implementation progress.

The CLI is intentionally a thin adapter over ``shared.implementation_store``.
It never selects a model, starts a worker, calls a network service, or writes
legacy views during ordinary progress operations.  Legacy readers are used
only by the explicit migration/rebuild commands.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
PLANS = ROOT / "scripts" / "plans"
for candidate in (str(HOOKS), str(PLANS)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from implementation_notes_lib import (  # noqa: E402
    ImplementationNotesError,
    ensure_not_red,
    infer_title,
    valid_non_initial_entries,
)
from shared.implementation_store import (  # noqa: E402
    CorruptRecordError,
    FutureSchemaError,
    IdempotencyError,
    ImplementationStore,
    IntegrityError,
    RedContentError,
    SchemaError,
    StoreError,
    StoreIOError,
    StorePathError,
    StoreResult,
    resolve_store_paths,
)
from shared.implementation_store.io import WriteMetadata  # noqa: E402
from shared.implementation_store.paths import PlanPaths, StorePaths, _reject_symlink_components, regular_file_stat  # noqa: E402
from shared.implementation_store.schema import (  # noqa: E402
    MATERIAL_EVENT_KINDS,
    VALID_STATUSES,
    canonical_json,
    digest,
)
from progress_context import (  # noqa: E402
    ContextError,
    ContextRequest,
    SourceResolution,
    derive_context_epoch,
    emit_context,
    legacy_fallback,
    resolve_context_source,
    select_new_state_source,
)
from legacy_migration import (  # noqa: E402
    MigrationError,
    _read_bounded_file,
    apply_migration,
    build_inventory,
    inventory_payload,
    rebuild_legacy_views,
)


CLI_VERSION = 1
MAX_TEXT_OUTPUT_BYTES = 16 * 1024
MAX_JSON_OUTPUT_BYTES = 512 * 1024
MAX_EXPORT_OUTPUT_BYTES = 256 * 1024
MAX_STATUS_EVENTS = 32
MAX_EXPORT_EVENTS = 512
MAX_MIGRATION_FILES = 2_000
MAX_MIGRATION_FILE_BYTES = 2 * 1024 * 1024
MAX_MIGRATION_SCAN_ENTRIES = MAX_MIGRATION_FILES * 4
VALID_RESULTS = frozenset({"not_run", "pending", "partial", "pass", "fail", "blocked"})
VALID_PROFILES = frozenset({"luna", "terra", "sol", "unknown"})
PROFILE_LIMITS = {"luna": 512, "terra": 192, "sol": 96, "unknown": 96}
LEGACY_NOTE_SUFFIX = "-implementation-notes.html"
LEGACY_INDEX_JSON = "implementation-index.json"
LEGACY_INDEX_MD = "implementation-index.md"
SENSITIVE_NAME_RE = re.compile(
    r"(?i)(^\.env(?:\.|$)|secret|token|credential|wallet|keystore|cookies?|id_rsa|id_ed25519|\.pem$|\.key$)"
)


class CliFailure(RuntimeError):
    """Stable, sanitized user-facing failure."""

    def __init__(self, code: str, message: str, exit_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


@dataclass(frozen=True)
class PlanRef:
    primary_root: Path
    plan_path: Path
    plan_rel: str
    plan_id: str

    @property
    def notes_path(self) -> Path:
        stem = self.plan_path.stem if self.plan_path.suffix else self.plan_path.name
        return self.plan_path.with_name(f"{stem}{LEGACY_NOTE_SUFFIX}")


def _safe_digest(value: Any) -> str:
    return digest(value)


def _emit_json(payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_JSON_OUTPUT_BYTES:
        raise CliFailure("output_limit", "CLI JSON output exceeds its bounded limit", 8)
    print(encoded)


def _digest_source(state: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> str:
    return _safe_digest({"state": dict(state), "events": [dict(event) for event in events]})


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _bounded_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _bounded_bytes(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    suffix = "..."
    room = max(0, limit - len(suffix.encode("utf-8")))
    return encoded[:room].decode("utf-8", errors="ignore") + suffix


def _safe_identifier(value: str | None, default: str) -> str:
    raw = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}", raw):
        return raw
    return default


def _git_output(root: Path, *args: str) -> str:
    try:
        import subprocess

        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=False, timeout=3
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _provenance(paths: StorePaths) -> dict[str, Any]:
    branch = _git_output(paths.primary_root, "branch", "--show-current") or _git_output(
        paths.primary_root, "rev-parse", "--abbrev-ref", "HEAD"
    )
    commit = _git_output(paths.primary_root, "rev-parse", "HEAD")
    workspace = "ws-" + hashlib.sha256(str(Path.cwd().resolve()).encode("utf-8")).hexdigest()[:16]
    return {
        "git": {"branch": _bounded_text(branch, 240), "commit": _bounded_text(commit, 64), "workspace_instance_id": workspace},
        "writer_session_id": _safe_identifier(
            os.environ.get("CODEX_SESSION_ID") or os.environ.get("RALPH_SESSION_ID"), "cli"
        ),
        "model_family": "unknown",
        "model_source": "unknown",
        "model_verified": False,
        "origin": "implementation-progress",
        "intent": "progress-maintenance",
    }


def _reject_sensitive_path(raw: str) -> None:
    if any(SENSITIVE_NAME_RE.search(part) for part in Path(raw).expanduser().parts):
        raise CliFailure("sensitive_path", "plan path is not allowed", 3)
    try:
        ensure_not_red("plan path", raw)
    except ImplementationNotesError as exc:
        raise CliFailure("red_content", "plan path contains RED-sensitive content", 3) from exc


def _relative_or_error(path: Path, root: Path, *, label: str) -> Path:
    try:
        return path.relative_to(root)
    except ValueError as exc:
        raise CliFailure("path_outside_repository", f"{label} must be inside the canonical repository", 6) from exc


def _resolve_plan(raw: str, paths: StorePaths) -> PlanRef:
    if not raw or "\x00" in raw or "\\" in raw:
        raise CliFailure("invalid_plan_path", "plan path is invalid", 2)
    _reject_sensitive_path(raw)
    candidate = Path(raw).expanduser()
    if any(part == ".." for part in candidate.parts):
        raise CliFailure("invalid_plan_path", "plan path is invalid", 2)
    active = Path.cwd().resolve()
    lexical = candidate if candidate.is_absolute() else active / candidate
    resolved = lexical.absolute()
    try:
        active_rel = resolved.relative_to(active)
    except ValueError:
        active_rel = None
    if active_rel is not None:
        canonical = paths.primary_root / active_rel
    else:
        canonical = resolved
    rel = _relative_or_error(canonical, paths.primary_root, label="plan path")
    if not rel.parts or rel.name in {"", ".", ".."}:
        raise CliFailure("invalid_plan_path", "plan path is invalid", 2)
    if rel.as_posix().startswith(".local-notes/ralph/implementation"):
        raise CliFailure("invalid_plan_path", "plan path cannot target the canonical store", 2)
    try:
        _reject_symlink_components(canonical, allow_missing=True)
        if canonical.exists():
            regular_file_stat(canonical)
    except (OSError, StorePathError, ValueError) as exc:
        raise CliFailure("invalid_plan_path", "plan path is an unsafe alias", 2) from exc
    plans_root = paths.primary_root / ".ralph" / "plans"
    try:
        plan_rel = canonical.relative_to(plans_root).as_posix()
    except ValueError:
        plan_rel = rel.as_posix()
    plan_id = Path(plan_rel).with_suffix("").as_posix() if Path(plan_rel).suffix in {".md", ".markdown"} else plan_rel
    if not plan_id:
        raise CliFailure("invalid_plan_path", "plan path is invalid", 2)
    try:
        # The store validator is the authoritative bounded plan-id check.
        from shared.implementation_store.paths import validate_plan_id

        validate_plan_id(plan_id)
    except (StorePathError, ValueError) as exc:
        raise CliFailure("invalid_plan_path", "plan path is invalid", 2) from exc
    return PlanRef(paths.primary_root, canonical, rel.as_posix(), plan_id)


def _store_for_plan(raw: str) -> tuple[ImplementationStore, StorePaths, PlanRef]:
    try:
        paths = resolve_store_paths(active_root=Path.cwd())
    except StorePathError as exc:
        raise CliFailure("store_path", "cannot resolve the canonical implementation store", 6) from exc
    return ImplementationStore(paths), paths, _resolve_plan(raw, paths)


def _metadata_payload(metadata: WriteMetadata) -> dict[str, Any]:
    return {
        "changed": metadata.changed,
        "bytes_written": metadata.bytes_written,
        "files_written": list(metadata.files_written),
        "replacements": metadata.replacements,
        "appends": metadata.appends,
        "fsync_publications": metadata.fsync_publications,
        "known": metadata.known,
    }


def _result_payload(command: str, ref: PlanRef, result: StoreResult, store: ImplementationStore | None = None) -> dict[str, Any]:
    state = result.state or {}
    events: tuple[dict[str, Any], ...] = store.read_events(ref.plan_id) if state and store is not None else ()
    return {
        "schema_version": CLI_VERSION,
        "ok": True,
        "command": command,
        "plan": ref.plan_rel,
        "plan_id": ref.plan_id,
        "changed": result.changed,
        "operation_id": result.operation_id,
        "event_id": result.event_id,
        "reason": result.reason,
        "metadata": _metadata_payload(result.metadata),
        "state": state or None,
        "source_digest": _digest_source(state, events) if state else "",
    }


def _state_and_events(store: ImplementationStore, ref: PlanRef) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    try:
        state = store.read_state(ref.plan_id)
        if state is None:
            raise CliFailure("plan_not_registered", "plan is not registered", 6)
        events = store.read_events(ref.plan_id)
    except CliFailure:
        raise
    except (FutureSchemaError, CorruptRecordError, IntegrityError) as exc:
        raise CliFailure("integrity_error", "implementation progress integrity verification failed", 5) from exc
    except StoreError as exc:
        raise CliFailure("store_error", "implementation progress store operation failed", 7) from exc
    return state, events


def _with_source(payload: dict[str, Any], state: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    payload["source_digest"] = _digest_source(state, events)
    return payload


def _event_summary(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sequence": event.get("sequence", 0),
        "event_id": event.get("event_id", ""),
        "operation_id": event.get("operation_id", ""),
        "timestamp": event.get("timestamp", ""),
        "kind": event.get("kind", ""),
        "summary": _bounded_text(event.get("summary", ""), 240),
        "reason": _bounded_text(event.get("reason", ""), 200),
        "next_action": _bounded_text(event.get("next_action", ""), 200),
        "status": event.get("status", ""),
        "phase": _bounded_text(event.get("phase", ""), 120),
    }


def _status_payload(ref: PlanRef, state: Mapping[str, Any], events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    omitted = max(0, len(events) - MAX_STATUS_EVENTS)
    selected = events[-MAX_STATUS_EVENTS:]
    return {
        "schema_version": CLI_VERSION,
        "ok": True,
        "command": "status",
        "plan": ref.plan_rel,
        "plan_id": ref.plan_id,
        "state": dict(state),
        "events": [_event_summary(event) for event in selected],
        "events_omitted": omitted,
        "source_digest": _digest_source(state, events),
    }


def _status_text(payload: Mapping[str, Any]) -> str:
    state = payload["state"]
    lines = [
        f"Plan: {payload['plan']}",
        f"Status: {state.get('status', '')}",
        f"Phase: {state.get('phase', '') or '(none)'}",
        f"Objective: {_bounded_text(state.get('objective', ''), 360) or '(none)'}",
        f"Next: {_bounded_text(state.get('next_action', ''), 360) or '(none)'}",
        f"Validation: {', '.join(f'{key}={value}' for key, value in sorted((state.get('validation') or {}).items())) or '(none)'}",
        f"Events: {len(payload.get('events', []))} (omitted={payload.get('events_omitted', 0)})",
        f"Source digest: {payload['source_digest']}",
    ]
    return "\n".join(lines)


def _context_capsule(ref: PlanRef, state: Mapping[str, Any], events: tuple[dict[str, Any], ...], profile: str) -> str:
    latest = events[-1] if events else {}
    validation = ",".join(f"{key}={value}" for key, value in sorted((state.get("validation") or {}).items()))
    lines = [
        f"plan={ref.plan_id}",
        f"status={state.get('status', '')} phase={state.get('phase', '') or '-'}",
        f"next={_bounded_text(state.get('next_action', ''), 180) or '-'}",
        f"validation={validation or '-'}",
        f"last={latest.get('kind', '-')}:{_bounded_text(latest.get('summary', ''), 180) or '-'}",
    ]
    return _bounded_bytes("\n".join(lines), PROFILE_LIMITS[profile])


def _html_escape(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _legacy_category(kind: str) -> str:
    return {
        "decision": "decision",
        "deviation": "deviation",
        "question_opened": "open-question",
        "question_resolved": "open-question",
        "validation_changed": "validation",
        "completed": "summary",
        "reopened": "decision",
        "migration_imported": "summary",
    }.get(kind, "decision")


def _legacy_html(ref: PlanRef, state: Mapping[str, Any], events: tuple[dict[str, Any], ...]) -> str:
    categories = ("decision", "deviation", "tradeoff", "open-question", "validation", "summary")
    grouped: dict[str, list[str]] = {category: [] for category in categories}
    for event in events:
        category = _legacy_category(str(event.get("kind", "")))
        summary = _html_escape(_bounded_text(event.get("summary", ""), 400))
        reason = _html_escape(_bounded_text(event.get("reason", ""), 400))
        next_action = _html_escape(_bounded_text(event.get("next_action", ""), 300))
        references = ", ".join(_html_escape(_bounded_text(item, 320)) for item in event.get("references", [])) or "n/a"
        operation = _html_escape(event.get("operation_id", ""))
        grouped[category].append(
            "    <article class=\"entry\" data-entry-kind=\"{category}\"><dl>"
            "<dt>Timestamp</dt><dd>{timestamp}</dd>"
            "<dt>Category</dt><dd>{category}</dd>"
            "<dt>Decision</dt><dd>{summary}</dd>"
            "<dt>Reason</dt><dd>{reason}</dd>"
            "<dt>Impact</dt><dd>{impact}</dd>"
            "<dt>Related files</dt><dd>{references}</dd>"
            "<dt>Status</dt><dd>{status}</dd>"
            "<dt>Operation ID</dt><dd>{operation}</dd></dl></article>\n".format(
                category=_html_escape(category),
                timestamp=_html_escape(event.get("timestamp", "")),
                summary=summary or "(none)",
                reason=reason or "(none)",
                impact=next_action or "(none)",
                references=references,
                status=_html_escape(event.get("status", state.get("status", ""))),
                operation=operation or "(none)",
            )
        )
    sections: list[str] = []
    labels = {
        "decision": "Design Decisions",
        "deviation": "Deviations From Spec",
        "tradeoff": "Tradeoffs Considered",
        "open-question": "Open Questions",
        "validation": "Validation Notes",
        "summary": "Final Implementation Summary",
    }
    for category in categories:
        anchor = f"IMPLEMENTATION_NOTES_{category.replace('-', '_').upper()}_ANCHOR"
        sections.append(
            f'    <section class="entry-section" data-entry-section="{_html_escape(category)}">\n'
            f"      <h2>{_html_escape(labels[category])}</h2>\n"
            f"{''.join(grouped[category])}      <!-- {anchor} -->\n    </section>"
        )
    title = _html_escape(ref.plan_path.stem)
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>Implementation Notes - {title}</title></head><body>\n"
        f"<main data-implementation-notes=\"true\"><h1>Implementation Notes - {title}</h1>\n"
        f"<p>Status: {_html_escape(state.get('status', ''))}; phase: {_html_escape(state.get('phase', ''))}</p>\n"
        f"{''.join(sections)}\n</main></body></html>\n"
    )


def _legacy_index(ref: PlanRef, state: Mapping[str, Any], events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    notes_rel = ref.notes_path.relative_to(ref.primary_root).as_posix()
    plan = {
        "type": "plan",
        "plan": ref.plan_rel,
        "notes": notes_rel,
        "status": "implemented" if state.get("status") == "completed" else state.get("status", "planned"),
        "branch": (state.get("git") or {}).get("branch", ""),
        "commits": [value for value in [(state.get("git") or {}).get("commit", "")] if value],
        "pr": "",
        "session_id": state.get("writer_session_id", ""),
        "workspace_instance_id": (state.get("git") or {}).get("workspace_instance_id", ""),
        "created_at": state.get("created_at", ""),
        "updated_at": state.get("updated_at", ""),
    }
    rendered_events = []
    for event in events:
        rendered_events.append(
            {
                "event": "notes_created" if event.get("kind") == "started" else "note_appended",
                "plan": ref.plan_rel,
                "notes": notes_rel,
                "status": event.get("status", ""),
                "branch": (event.get("git") or {}).get("branch", ""),
                "commit": (event.get("git") or {}).get("commit", ""),
                "session_id": event.get("writer_session_id", ""),
                "operation_id": event.get("operation_id", ""),
                "timestamp": event.get("timestamp", ""),
                "event_id": event.get("event_id", ""),
                "kind": event.get("kind", ""),
                "summary": _bounded_text(event.get("summary", ""), 400),
            }
        )
    return {
        "version": 2,
        "canonical_repo_root": str(ref.primary_root),
        "updated_at": state.get("updated_at", ""),
        "plans": [plan],
        "loose_commits": [],
        "events": rendered_events,
    }


def _legacy_index_markdown(index: Mapping[str, Any]) -> str:
    lines = [
        "# Implementation Index",
        "",
        f"Version: {index.get('version', 2)}",
        "",
        "## Plans",
        "",
        "| Plan | Status | Branch | Commits |",
        "| --- | --- | --- | --- |",
    ]
    for plan in index.get("plans", []):
        commits = ", ".join(str(value) for value in plan.get("commits", [])) or "-"
        lines.append(
            f"| {plan.get('plan', '')} | {plan.get('status', '')} | {plan.get('branch', '')} | {commits} |"
        )
    lines.extend(["", "## Implementation Events", ""])
    for event in index.get("events", []):
        lines.append(
            f"- [{event.get('timestamp', '')}] {event.get('kind', event.get('event', ''))}: "
            f"{_bounded_text(event.get('summary', ''), 300)} (operation {event.get('operation_id', '')})"
        )
    return "\n".join(lines) + "\n"


def _markdown_export(ref: PlanRef, state: Mapping[str, Any], events: tuple[dict[str, Any], ...]) -> str:
    lines = [
        f"# Implementation Progress: {ref.plan_id}",
        "",
        f"- Plan: `{ref.plan_rel}`",
        f"- Status: `{state.get('status', '')}`",
        f"- Phase: `{state.get('phase', '')}`",
        f"- Next: {_bounded_text(state.get('next_action', ''), 400) or '(none)' }",
        f"- Objective: {_bounded_text(state.get('objective', ''), 480) or '(none)' }",
        "",
        "## Validation",
        "",
    ]
    validation = state.get("validation") or {}
    lines.extend(f"- `{gate}`: `{result}`" for gate, result in sorted(validation.items()))
    if not validation:
        lines.append("- None recorded.")
    lines.extend(["", "## Timeline", ""])
    selected = events[-MAX_EXPORT_EVENTS:]
    for event in selected:
        lines.append(
            f"- `{event.get('sequence', '')}` `{event.get('timestamp', '')}` "
            f"**{event.get('kind', '')}** — {_bounded_text(event.get('summary', ''), 400) or '(none)'} "
            f"(operation `{event.get('operation_id', '')}`)"
        )
    if len(events) > len(selected):
        lines.append(f"- ... {len(events) - len(selected)} earlier events omitted from the view.")
    return "\n".join(lines) + "\n"


def _consolidated_export(ref: PlanRef, state: Mapping[str, Any], events: tuple[dict[str, Any], ...]) -> str:
    return "\n".join(
        [
            f"# Consolidated Implementation History: {ref.plan_id}",
            "",
            f"Source plan: `{ref.plan_rel}`",
            f"Current status: `{state.get('status', '')}`",
            "",
            _markdown_export(ref, state, events).split("## Timeline", 1)[-1].lstrip(),
        ]
    )


def _render_export(fmt: str, ref: PlanRef, state: Mapping[str, Any], events: tuple[dict[str, Any], ...]) -> str:
    if fmt == "markdown":
        return _markdown_export(ref, state, events)
    if fmt == "html":
        return _legacy_html(ref, state, events)
    if fmt == "legacy-index":
        return json.dumps(_legacy_index(ref, state, events), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if fmt == "consolidated":
        return _consolidated_export(ref, state, events)
    raise CliFailure("invalid_export_format", "unsupported export format", 2)


def _write_explicit_view(store: ImplementationStore, output: str, content: str) -> WriteMetadata:
    if not output:
        raise CliFailure("output_required", "an explicit output path is required for persistence", 2)
    try:
        return store.publish_derived_view(output, content)
    except (StorePathError, StoreIOError) as exc:
        raise CliFailure("export_output", "cannot persist the requested derived view", 8) from exc


def _record_update_for_kind(state: Mapping[str, Any], kind: str, summary: str) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if kind in {"decision", "deviation", "migration_imported"} and summary:
        updates["latest_decision"] = {"event_id": "pending", "summary": summary}
    elif kind == "question_opened":
        questions = list(state.get("open_questions") or [])
        if summary not in questions:
            questions.append(summary)
        updates["open_questions"] = questions[-8:]
    elif kind == "question_resolved":
        updates["open_questions"] = [value for value in state.get("open_questions", []) if value != summary]
    elif kind == "blocker_opened":
        blockers = list(state.get("open_blockers") or [])
        if summary not in blockers:
            blockers.append(summary)
        updates["open_blockers"] = blockers[-8:]
    elif kind == "blocker_resolved":
        updates["open_blockers"] = [value for value in state.get("open_blockers", []) if value != summary]
    return updates


def _require_result(value: str) -> str:
    if value not in VALID_RESULTS:
        raise CliFailure("invalid_validation_result", "validation result is unsupported", 2)
    return value


def _apply_result(command: str, ref: PlanRef, result: StoreResult, *, json_mode: bool, store: ImplementationStore | None = None) -> int:
    payload = _result_payload(command, ref, result, store)
    if json_mode:
        _emit_json(payload)
    else:
        print(
            f"{command.upper()} {'CHANGED' if result.changed else 'NOOP'} "
            f"plan_id={ref.plan_id} operation_id={result.operation_id} reason={result.reason or 'material update'}"
        )
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    store, paths, ref = _store_for_plan(args.plan)
    result = store.register_plan(
        ref.plan_id,
        plan_path=ref.plan_rel,
        operation_id=args.operation_id,
        provenance=_provenance(paths),
        objective=args.objective or "",
        phase=args.phase or "",
        next_action=args.next_action or "",
        status="active",
    )
    return _apply_result("start", ref, result, json_mode=args.json or args.output_format == "json", store=store)


def _cmd_record(args: argparse.Namespace) -> int:
    store, paths, ref = _store_for_plan(args.plan)
    state, _events = _state_and_events(store, ref)
    if args.kind == "loose_commit_recorded":
        raise CliFailure("invalid_event_kind", "loose commits require the unplanned-event API", 2)
    if args.kind not in MATERIAL_EVENT_KINDS:
        raise CliFailure("invalid_event_kind", "event kind is unsupported", 2)
    result = store.record_event(
        ref.plan_id,
        kind=args.kind,
        operation_id=args.operation_id,
        summary=args.summary,
        state_update=_record_update_for_kind(state, args.kind, args.summary),
        provenance=_provenance(paths),
    )
    return _apply_result("record", ref, result, json_mode=args.json or args.output_format == "json", store=store)


def _cmd_phase(args: argparse.Namespace) -> int:
    store, paths, ref = _store_for_plan(args.plan)
    result = store.record_event(
        ref.plan_id,
        kind="phase_changed",
        operation_id=args.operation_id,
        summary=f"Phase changed to {args.phase}",
        next_action=args.next_action,
        state_update={"phase": args.phase},
        provenance=_provenance(paths),
    )
    return _apply_result("phase", ref, result, json_mode=args.json or args.output_format == "json", store=store)


def _cmd_validate(args: argparse.Namespace) -> int:
    result_value = _require_result(args.result)
    store, paths, ref = _store_for_plan(args.plan)
    state, _events = _state_and_events(store, ref)
    validation = dict(state.get("validation") or {})
    validation[args.gate] = result_value
    result = store.record_event(
        ref.plan_id,
        kind="validation_changed",
        operation_id=args.operation_id,
        summary=f"Validation {args.gate}: {result_value}",
        state_update={"validation": validation},
        provenance=_provenance(paths),
    )
    return _apply_result("validate", ref, result, json_mode=args.json or args.output_format == "json", store=store)


def _cmd_status(args: argparse.Namespace) -> int:
    store, _paths, ref = _store_for_plan(args.plan)
    state, events = _state_and_events(store, ref)
    payload = _status_payload(ref, state, events)
    if args.json or args.output_format == "json":
        _emit_json(payload)
    else:
        print(_status_text(payload))
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    if args.profile not in VALID_PROFILES:
        raise CliFailure("invalid_profile", "context profile is unsupported", 2)
    store, paths, ref = _store_for_plan(args.plan)
    workspace_instance_id = _safe_identifier(
        args.workspace_instance_id,
        "ws-" + hashlib.sha256(str(Path.cwd().resolve()).encode("utf-8")).hexdigest()[:16],
    )
    project_id = _safe_identifier(
        args.project_id,
        "repo-" + hashlib.sha256(str(paths.primary_root).encode("utf-8")).hexdigest()[:24],
    )
    session_id = _safe_identifier(
        args.session_id or os.environ.get("CODEX_SESSION_ID") or os.environ.get("RALPH_SESSION_ID"),
        "unknown",
    )
    context_epoch = args.context_epoch or derive_context_epoch(None, args.event, session_id)
    try:
        new_resolution = select_new_state_source(
            store,
            plan_id=ref.plan_id,
            workspace_instance_id=workspace_instance_id,
        )
    except (FutureSchemaError, CorruptRecordError, IntegrityError) as exc:
        new_resolution = SourceResolution(None, "state_invalid")
        state_error = exc
    else:
        state_error = None

    resolution = resolve_context_source(
        new_resolution=new_resolution,
        legacy_loader=lambda: legacy_fallback(plan_id=ref.plan_id, notes_path=ref.notes_path),
        recovery_boundary=args.event in {"startup", "new-session", "resume", "compact", "explicit", "external"},
    )
    if resolution.source is None:
        if state_error is not None:
            raise CliFailure("integrity_error", "implementation progress integrity verification failed", 5) from state_error
        raise CliFailure("plan_not_registered", "plan is not registered", 6)
    request = ContextRequest(
        profile=args.profile,
        verified=not args.unverified and args.profile != "unknown",
        project_id=project_id,
        workspace_instance_id=workspace_instance_id,
        session_id=session_id,
        context_epoch=context_epoch,
        event=args.event,
        external_writer=args.external_writer,
        same_session_write=args.same_session_write,
    )
    decision = emit_context(resolution.source, request, ledger=store)
    payload = {
        "schema_version": CLI_VERSION,
        "ok": True,
        "command": "context",
        "plan": ref.plan_rel,
        "plan_id": ref.plan_id,
        "profile": args.profile,
        "event": args.event,
        "context_epoch": context_epoch,
        "session_id": session_id,
        "source": decision.source,
        "selection_reason": resolution.reason,
        "fallback_used": resolution.fallback_used,
        "emitted": decision.emitted,
        "capsule_kind": decision.capsule_kind,
        "reason": decision.reason,
        "ledger_hit": decision.ledger_hit,
        "progress_generation": decision.progress_generation,
        "budget_bytes": PROFILE_LIMITS[args.profile] if args.profile in PROFILE_LIMITS else 96,
        "capsule": decision.capsule,
        "word_count": len(decision.capsule.split()),
        "source_digest": decision.source_digest,
        "output_digest": decision.output_digest,
    }
    if args.json or args.output_format == "json":
        _emit_json(payload)
    else:
        if decision.capsule:
            print(decision.capsule)
        else:
            print(f"CONTEXT_NOOP reason={decision.reason} plan_id={ref.plan_id}")
        print(f"SOURCE_DIGEST={payload['source_digest']} OUTPUT_DIGEST={payload['output_digest']} EMITTED={str(decision.emitted).lower()}")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    store, paths, ref = _store_for_plan(args.plan)
    state, events = _state_and_events(store, ref)
    content = _render_export(args.export_format, ref, state, events)
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > MAX_EXPORT_OUTPUT_BYTES:
        raise CliFailure("output_limit", "derived export exceeds its bounded output limit", 8)
    if not args.json and content_bytes > MAX_TEXT_OUTPUT_BYTES:
        raise CliFailure("output_limit", "text export exceeds its bounded stdout limit; use --json or --output", 8)
    source_digest = _digest_source(state, events)
    output_digest = _digest_bytes(content.encode("utf-8"))
    metadata = WriteMetadata()
    output_path = args.output
    if args.apply and not output_path:
        suffix = {"markdown": "md", "html": "html", "legacy-index": "json", "consolidated": "md"}[args.export_format]
        output_path = str(paths.root / "exports" / f"{ref.plan_id.replace('/', '__')}.{suffix}")
    if output_path:
        metadata = _write_explicit_view(store, output_path, content)
    payload = {
        "schema_version": CLI_VERSION,
        "ok": True,
        "command": "export",
        "plan": ref.plan_rel,
        "plan_id": ref.plan_id,
        "format": args.export_format,
        "content": content,
        "source_digest": source_digest,
        "output_digest": output_digest,
        "output": output_path or "",
        "persisted": bool(output_path),
        "metadata": _metadata_payload(metadata),
    }
    if args.json:
        _emit_json(payload)
    else:
        print(content, end="" if content.endswith("\n") else "\n")
        print(f"SOURCE_DIGEST={source_digest} OUTPUT_DIGEST={output_digest} PERSISTED={str(bool(output_path)).lower()}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    store, _paths, ref = _store_for_plan(args.plan)
    state, events = _state_and_events(store, ref)
    payload = {
        "schema_version": CLI_VERSION,
        "ok": True,
        "command": "verify",
        "plan": ref.plan_rel,
        "plan_id": ref.plan_id,
        "event_count": len(events),
        "generation": state.get("generation", 0),
        "source_digest": _digest_source(state, events),
        "state_semantic_hash": state.get("semantic_hash", ""),
    }
    if args.json or args.output_format == "json":
        _emit_json(payload)
    else:
        print(
            f"VERIFY_PASS plan_id={ref.plan_id} events={len(events)} "
            f"source_digest={payload['source_digest']}"
        )
    return 0


@dataclass(frozen=True)
class LegacyFile:
    path: Path
    kind: str
    digest: str
    bytes: int


def _legacy_files(primary_root: Path) -> tuple[LegacyFile, ...]:
    root = primary_root / ".ralph" / "plans"
    if not root.exists():
        return ()
    files: list[LegacyFile] = []
    pending = [root]
    scanned = 0
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError as exc:
            raise CliFailure("legacy_error", "legacy artifact directory cannot be scanned", 8) from exc
        for entry in entries:
            scanned += 1
            if scanned > MAX_MIGRATION_SCAN_ENTRIES:
                raise CliFailure("legacy_limit", "legacy directory traversal exceeds the migration limit", 8)
            path = Path(entry.path)
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
                continue
            if len(files) >= MAX_MIGRATION_FILES:
                raise CliFailure("legacy_limit", "legacy artifact count exceeds the migration limit", 8)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise CliFailure("legacy_error", "legacy artifact cannot be inspected", 8) from exc
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                continue
            if any(SENSITIVE_NAME_RE.search(part) for part in path.relative_to(primary_root).parts):
                raise CliFailure("sensitive_path", "legacy artifact path is not allowed", 3)
            name = path.name
            if name == LEGACY_INDEX_JSON:
                kind = "index-json"
            elif name == LEGACY_INDEX_MD:
                kind = "index-markdown"
            elif name == "implementation-notes-consolidated.md" or name.endswith("-implementation-notes-consolidated.md"):
                kind = "consolidated-markdown"
            elif name == "implementation-notes-consolidated.html" or name.endswith("-implementation-notes-consolidated.html"):
                kind = "consolidated-html"
            elif name.endswith(LEGACY_NOTE_SUFFIX):
                kind = "notes-html"
            elif path.suffix.lower() in {".md", ".markdown"}:
                kind = "plan-markdown"
            else:
                continue
            size = int(info.st_size)
            if size > MAX_MIGRATION_FILE_BYTES:
                raise CliFailure("legacy_limit", "legacy artifact exceeds the migration limit", 8)
            try:
                raw, _ = _read_bounded_file(path, max_bytes=MAX_MIGRATION_FILE_BYTES, expected_inode=(info.st_dev, info.st_ino))
            except (OSError, MigrationError) as exc:
                raise CliFailure("legacy_error", "legacy artifact changed during inventory", 8) from exc
            files.append(LegacyFile(path, kind, _digest_bytes(raw), len(raw)))
    return tuple(files)


def _legacy_plan_candidates(primary_root: Path, files: tuple[LegacyFile, ...]) -> list[tuple[Path, Path | None]]:
    plans = {item.path for item in files if item.kind == "plan-markdown"}
    notes = {item.path for item in files if item.kind == "notes-html"}
    candidates: list[tuple[Path, Path | None]] = []
    for plan in sorted(plans):
        inferred = plan.with_name(f"{plan.stem}{LEGACY_NOTE_SUFFIX}")
        candidates.append((plan, inferred if inferred in notes else None))
    for note in sorted(notes):
        if any(note == candidate[1] for candidate in candidates):
            continue
        pseudo = note.with_name(note.name[: -len(LEGACY_NOTE_SUFFIX)] + ".md")
        candidates.append((pseudo, note))
    return candidates


def _migration_payload(primary: Path, files: tuple[LegacyFile, ...], candidates: list[tuple[Path, Path | None]]) -> dict[str, Any]:
    source = [{"path": file.path.relative_to(primary).as_posix(), "kind": file.kind, "digest": file.digest, "bytes": file.bytes} for file in files]
    return {
        "schema_version": CLI_VERSION,
        "ok": True,
        "command": "migrate-legacy",
        "mode": "inventory",
        "canonical_repo_root": str(primary),
        "file_count": len(files),
        "plan_count": len(candidates),
        "files": source,
        "source_digest": _safe_digest(source),
    }


def _legacy_entries(note_path: Path) -> list[Any]:
    try:
        raw, _ = _read_bounded_file(note_path, max_bytes=MAX_MIGRATION_FILE_BYTES)
        text = raw.decode("utf-8")
        ensure_not_red("legacy implementation notes", text)
        return valid_non_initial_entries(text, include_summary=True)
    except (OSError, UnicodeError, ImplementationNotesError, MigrationError) as exc:
        raise CliFailure("legacy_invalid", "legacy implementation notes are invalid", 8) from exc


def _migration_event_kind(category: str, status: str) -> str:
    normalized = status.lower()
    if category == "validation":
        return "validation_changed"
    if category == "open-question":
        return "question_resolved" if normalized in {"resolved", "closed", "complete"} else "question_opened"
    if normalized in {"blocked", "blocker", "blocked-open"}:
        return "blocker_opened"
    if normalized in {"resolved", "closed", "complete", "implemented"}:
        return "completed"
    if category == "deviation":
        return "deviation"
    if category == "summary":
        return "migration_imported"
    return "decision"


def _migration_operation(entry: Any, note_path: Path, primary: Path) -> str:
    supplied = entry.fields.get("Operation ID", "")
    if supplied and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}", supplied):
        return supplied
    material = "\n".join(
        [
            note_path.relative_to(primary).as_posix(),
            entry.category,
            entry.fields.get("Timestamp", ""),
            entry.fields.get("Decision", ""),
            entry.fields.get("Status", ""),
        ]
    )
    return "mig-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def _cmd_migrate(args: argparse.Namespace) -> int:
    if bool(args.dry_run) == bool(args.apply):
        raise CliFailure("migration_mode_required", "choose exactly one of --dry-run or --apply", 2)
    try:
        paths = resolve_store_paths(active_root=Path.cwd())
    except StorePathError as exc:
        raise CliFailure("store_path", "cannot resolve the canonical implementation store", 6) from exc
    context = build_inventory(paths, active_root=Path.cwd(), recovery_mode=bool(args.recovery_mode))
    inventory = inventory_payload(context)
    if args.dry_run:
        if args.json or args.output_format == "json":
            _emit_json(inventory)
        else:
            print(
                f"MIGRATE_DRY_RUN files={inventory['file_count']} plans={inventory['plan_count']} "
                f"source_digest={inventory['source_digest']}"
            )
        return 0
    try:
        payload = apply_migration(context, recovery_mode=bool(args.recovery_mode))
    except MigrationError as exc:
        report = exc.report or inventory
        raise CliFailure(exc.code, exc.message, 8) from exc
    if args.json or args.output_format == "json":
        _emit_json(payload)
    else:
        print(
            f"MIGRATE_APPLIED files={inventory['file_count']} plans={payload['imported_plans']} "
            f"events={payload['imported_events']} source_digest={inventory['source_digest']} output_digest={payload['output_digest']}"
        )
    return 0


def _cmd_rebuild(args: argparse.Namespace) -> int:
    try:
        paths = resolve_store_paths(active_root=Path.cwd())
        store = ImplementationStore(paths)
        selected_plan = _resolve_plan(args.plan, paths).plan_id if args.plan else None
        payload = rebuild_legacy_views(store, apply=bool(args.apply), plan_id=selected_plan)
    except MigrationError as exc:
        raise CliFailure(exc.code, exc.message, 8) from exc
    except (StorePathError, StoreError, StoreIOError, IntegrityError, FutureSchemaError, CorruptRecordError) as exc:
        raise CliFailure("rollback_failed", "legacy rollback export failed", 8) from exc
    if args.json or args.output_format == "json":
        _emit_json(payload)
    else:
        print(
            f"REBUILD_LEGACY_{'APPLIED' if payload.get('applied') else 'DRY_RUN'} "
            f"plans={len(payload.get('plans', []))} outputs={len(payload.get('outputs', []))} "
            f"source_digest={payload['source_digest']} output_digest={payload['output_digest']}"
        )
    return 0


def _add_json_flags(parser: argparse.ArgumentParser, *, format_default: str = "text") -> None:
    parser.add_argument("--json", action="store_true", help="Emit one bounded JSON result.")
    parser.add_argument("--format", dest="output_format", choices=("json", "text"), default=format_default)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic implementation-progress operations.")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Register a plan in the canonical store.")
    start.add_argument("--plan", required=True)
    start.add_argument("--objective", default="")
    start.add_argument("--phase", default="")
    start.add_argument("--next", dest="next_action", default="")
    start.add_argument("--operation-id")
    _add_json_flags(start)
    start.set_defaults(handler=_cmd_start)

    record = sub.add_parser("record", help="Record one bounded material event.")
    record.add_argument("--plan", required=True)
    record.add_argument("--kind", required=True)
    record.add_argument("--summary", required=True)
    record.add_argument("--operation-id")
    _add_json_flags(record)
    record.set_defaults(handler=_cmd_record)

    phase = sub.add_parser("phase", help="Record a phase transition.")
    phase.add_argument("--plan", required=True)
    phase.add_argument("--phase", required=True)
    phase.add_argument("--next", dest="next_action", required=True)
    phase.add_argument("--operation-id")
    _add_json_flags(phase)
    phase.set_defaults(handler=_cmd_phase)

    validate = sub.add_parser("validate", help="Record a validation gate result.")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--gate", required=True)
    validate.add_argument("--result", required=True)
    validate.add_argument("--operation-id")
    _add_json_flags(validate)
    validate.set_defaults(handler=_cmd_validate)

    status = sub.add_parser("status", help="Render bounded current state.")
    status.add_argument("--plan", required=True)
    _add_json_flags(status)
    status.set_defaults(handler=_cmd_status)

    context = sub.add_parser("context", help="Render a profile-bounded recovery capsule.")
    context.add_argument("--plan", required=True)
    context.add_argument("--profile", required=True, choices=sorted(VALID_PROFILES))
    context.add_argument(
        "--event",
        choices=("ordinary", "startup", "new-session", "resume", "compact", "clear", "reset", "explicit", "external"),
        default="explicit",
        help="Lifecycle boundary that controls recovery emission; explicit is the CLI default.",
    )
    context.add_argument("--session-id", default="")
    context.add_argument("--workspace-instance-id", default="")
    context.add_argument("--project-id", default="")
    context.add_argument("--context-epoch", default="")
    context.add_argument("--unverified", action="store_true", help="Use the conservative unverified-model budget.")
    context.add_argument("--external-writer", action="store_true", help="The current snapshot was written by another session.")
    context.add_argument("--same-session-write", action="store_true", help="The current session wrote the snapshot; suppress recovery.")
    _add_json_flags(context)
    context.set_defaults(handler=_cmd_context)

    export = sub.add_parser("export", help="Render an explicit derived view.")
    export.add_argument("--plan", required=True)
    export.add_argument("--format", dest="export_format", required=True, choices=("markdown", "html", "legacy-index", "consolidated"))
    export.add_argument("--output", default="")
    export.add_argument("--apply", action="store_true", help="Persist to the canonical derived-view location when --output is omitted.")
    export.add_argument("--json", action="store_true")
    export.set_defaults(handler=_cmd_export)

    verify = sub.add_parser("verify", help="Verify state and journal integrity.")
    verify.add_argument("--plan", required=True)
    _add_json_flags(verify)
    verify.set_defaults(handler=_cmd_verify)

    migrate = sub.add_parser("migrate-legacy", help="Inventory or explicitly import legacy artifacts.")
    mode = migrate.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    migrate.add_argument("--json", action="store_true")
    migrate.add_argument("--format", dest="output_format", choices=("json", "text"), default="text")
    migrate.add_argument("--recovery-mode", action="store_true", help="Explicitly proceed with selected evidence despite inventory conflicts.")
    migrate.set_defaults(handler=_cmd_migrate, dry_run=False, apply=False)

    rebuild = sub.add_parser("rebuild-legacy", help="Preview or explicitly rebuild compatibility views from new state.")
    rebuild.add_argument("--plan", required=False)
    rebuild.add_argument("--apply", action="store_true", help="Replace legacy views only after staged output validation.")
    _add_json_flags(rebuild)
    rebuild.set_defaults(handler=_cmd_rebuild)
    return parser


def _error_from_exception(exc: BaseException) -> CliFailure:
    if isinstance(exc, CliFailure):
        return exc
    if isinstance(exc, MigrationError):
        return CliFailure(exc.code, exc.message, 8)
    if isinstance(exc, RedContentError):
        return CliFailure("red_content", "input contains RED-sensitive content", 3)
    if isinstance(exc, IdempotencyError):
        return CliFailure("idempotency_conflict", "operation ID conflicts with an existing payload", 4)
    if isinstance(exc, (FutureSchemaError, CorruptRecordError, IntegrityError)):
        return CliFailure("integrity_error", "implementation progress integrity verification failed", 5)
    if isinstance(exc, StorePathError):
        return CliFailure("store_path", "implementation progress path is unsafe", 6)
    if isinstance(exc, StoreIOError):
        return CliFailure("store_io", "implementation progress storage failed", 7)
    if isinstance(exc, SchemaError):
        return CliFailure("schema_error", "input does not satisfy the bounded progress schema", 2)
    if isinstance(exc, ContextError):
        return CliFailure("context_error", "progress recovery context is invalid or exceeds its bound", 8)
    if isinstance(exc, StoreError):
        message = "plan is not registered" if "not registered" in str(exc) else "implementation progress operation failed"
        return CliFailure("plan_not_registered" if message == "plan is not registered" else "store_error", message, 6 if message == "plan is not registered" else 7)
    if isinstance(exc, (ImplementationNotesError, OSError, ValueError)):
        return CliFailure("legacy_error", "legacy compatibility operation failed", 8)
    return CliFailure("internal_error", "implementation progress operation failed", 1)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        return int(args.handler(args))
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - the CLI boundary sanitizes every failure.
        failure = _error_from_exception(exc)
        json_mode = False
        if "args" in locals():
            json_mode = bool(getattr(args, "json", False) or getattr(args, "output_format", "") == "json")
        payload = {
            "schema_version": CLI_VERSION,
            "ok": False,
            "error": {"code": failure.code, "message": failure.message},
        }
        if json_mode:
            _emit_json(payload)
        else:
            print(f"ERROR[{failure.code}] {failure.message}", file=sys.stderr)
        return failure.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
