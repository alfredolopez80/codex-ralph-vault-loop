"""Pure recovery-only progress context selection and rendering.

This module has no hook registration and no model/runtime dependencies.  It
turns one validated store snapshot (or one bounded legacy recovery parse) into
an intentionally small model-visible capsule.  The store owns the shared
content-free emission ledger; this module only decides when a non-empty
capsule is eligible to claim a key.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from implementation_notes_lib import ensure_not_red, valid_non_initial_entries


PROFILES = frozenset({"luna", "terra", "sol", "unknown"})
CONTEXT_EVENTS = frozenset({"ordinary", "startup", "new-session", "resume", "compact", "clear", "reset", "explicit", "external"})
CAPSULE_KINDS = frozenset({"full", "delta", "expanded"})
ACTIVE_STATUSES = frozenset({"active"})
UNKNOWN_SESSION = "unknown"
LUNA_FULL_BYTES = 512
LUNA_DELTA_BYTES = 256
LUNA_EXPANDED_BYTES = 1024
TERRA_BYTES = 192
POINTER_BYTES = 96
LUNA_FULL_WORDS = 80
LUNA_DELTA_WORDS = 35
LUNA_EXPANDED_WORDS = 180
LEGACY_FALLBACK_MAX_BYTES = 2 * 1024 * 1024
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")
_HASH_RE = re.compile(r"(?i)sha256:[0-9a-f]{8,64}")
_HEX_HASH_RE = re.compile(r"(?<![A-Za-z0-9])[0-9a-f]{7,64}(?![A-Za-z0-9])", re.IGNORECASE)
_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9])/(?:[^\s,;]+)")
_WINDOWS_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\[^\s,;]+")


class ContextError(ValueError):
    """Raised when a context identity or epoch cannot be bounded safely."""


class LedgerLike(Protocol):
    def claim_context_emission(self, record: Mapping[str, Any]) -> Any:
        ...


@dataclass(frozen=True)
class ContextRequest:
    profile: str = "luna"
    verified: bool = True
    project_id: str = "project"
    workspace_instance_id: str = "workspace"
    session_id: str = UNKNOWN_SESSION
    context_epoch: str = "epoch"
    event: str = "ordinary"
    external_writer: bool = False
    same_session_write: bool = False

    def checked(self) -> "ContextRequest":
        profile = self.profile if self.profile in PROFILES else "unknown"
        event = self.event if self.event in CONTEXT_EVENTS else "ordinary"
        return ContextRequest(
            profile=profile,
            verified=bool(self.verified),
            project_id=_identifier(self.project_id, "project"),
            workspace_instance_id=_identifier(self.workspace_instance_id, "workspace"),
            session_id=_identifier(self.session_id, UNKNOWN_SESSION),
            context_epoch=_identifier(self.context_epoch, "epoch"),
            event=event,
            external_writer=bool(self.external_writer),
            same_session_write=bool(self.same_session_write),
        )


@dataclass(frozen=True)
class ContextSource:
    plan_id: str
    state: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...] = ()
    source: str = "state"

    @property
    def generation(self) -> int:
        value = self.state.get("generation", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


@dataclass(frozen=True)
class SourceResolution:
    source: ContextSource | None
    reason: str
    fallback_used: bool = False


@dataclass(frozen=True)
class ContextDecision:
    emitted: bool
    capsule: str
    capsule_kind: str
    reason: str
    source: str
    ledger_hit: bool
    progress_generation: int
    source_digest: str
    output_digest: str


def _identifier(value: object, default: str) -> str:
    text = str(value or "").strip()
    if _IDENTIFIER_RE.fullmatch(text):
        return text
    return default


def _clean(value: object, limit: int = 360) -> str:
    text = " ".join(str(value or "").split())
    text = _HASH_RE.sub("", text)
    text = _HEX_HASH_RE.sub("", text)
    text = _ABSOLUTE_PATH_RE.sub("repo-file", text)
    text = _WINDOWS_PATH_RE.sub("repo-file", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def _source_digest(source: ContextSource) -> str:
    material = {"plan_id": source.plan_id, "state": dict(source.state), "events": [dict(item) for item in source.events], "source": source.source}
    return "sha256:" + hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _output_digest(capsule: str) -> str:
    return "sha256:" + hashlib.sha256(capsule.encode("utf-8")).hexdigest()


def derive_context_epoch(previous: str | None, event: str, session_id: str) -> str:
    """Return a deterministic epoch, advancing at every platform boundary."""

    normalized_event = event if event in CONTEXT_EVENTS else "ordinary"
    session = _identifier(session_id, UNKNOWN_SESSION)
    prior = _identifier(previous, "") if previous else ""
    if normalized_event in {"startup", "new-session"}:
        return f"startup:{session}"
    if normalized_event == "resume":
        return f"resume:{session}"
    if normalized_event == "compact":
        return f"compact:{session}"
    if normalized_event in {"clear", "reset"}:
        return f"reset:{session}"
    if normalized_event == "explicit":
        return f"explicit:{session}"
    return prior or f"session:{session}"


def _state_source(store: Any, plan_id: str, *, source_label: str = "state") -> ContextSource | None:
    state = store.read_state(plan_id)
    if state is None:
        return None
    events = tuple(store.read_events(plan_id))
    return ContextSource(plan_id=plan_id, state=state, events=events, source=source_label)


def select_new_state_source(
    store: Any,
    *,
    plan_id: str | None = None,
    workspace_instance_id: str = "",
) -> SourceResolution:
    """Select one current-schema plan, refusing ambiguous automatic matches."""

    if plan_id:
        source = _state_source(store, plan_id)
        return SourceResolution(source, "explicit_state" if source else "state_missing")

    manifest = store.read_manifest()
    if not manifest:
        return SourceResolution(None, "state_unavailable")
    candidates: list[ContextSource] = []
    for pointer in manifest.get("plans", []):
        if not isinstance(pointer, Mapping) or pointer.get("status") not in ACTIVE_STATUSES:
            continue
        pointer_workspace = str(pointer.get("workspace_instance_id") or "")
        if workspace_instance_id and pointer_workspace != workspace_instance_id:
            continue
        candidate_id = str(pointer.get("plan_id") or "")
        if not candidate_id:
            continue
        try:
            source = _state_source(store, candidate_id)
        except Exception:  # malformed candidates are ineligible, not a reason to select another plan
            source = None
        if source is None or source.state.get("status") not in ACTIVE_STATUSES:
            continue
        candidates.append(source)
    if len(candidates) == 1:
        return SourceResolution(candidates[0], "single_active_state")
    if len(candidates) > 1:
        return SourceResolution(None, "ambiguous_active_state")
    return SourceResolution(None, "no_active_state")


def _legacy_source_from_text(plan_id: str, text: str, *, parse: Callable[..., list[Any]] = valid_non_initial_entries) -> ContextSource:
    """Parse one legacy HTML body exactly once for a fallback operation."""

    ensure_not_red("legacy implementation notes", text)
    entries = parse(text, include_summary=True)
    events: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        fields = entry.fields
        events.append(
            {
                "sequence": index,
                "kind": entry.category,
                "summary": fields.get("Decision", ""),
                "reason": fields.get("Reason", ""),
                "next_action": fields.get("Impact", ""),
                "status": fields.get("Status", ""),
            }
        )
    latest = events[-1] if events else {}
    state = {
        "plan_id": plan_id,
        "generation": 0,
        "status": "active",
        "phase": "",
        "objective": "",
        "latest_decision": {"summary": latest.get("summary", "")} if latest else None,
        "next_action": latest.get("next_action", ""),
        "open_blockers": [],
        "open_questions": [],
        "validation": {},
        "writer_session_id": "",
    }
    return ContextSource(plan_id=plan_id, state=state, events=tuple(events), source="legacy")


def legacy_fallback(
    *,
    plan_id: str,
    notes_path: Path | None,
    parser: Callable[..., list[Any]] = valid_non_initial_entries,
) -> ContextSource | None:
    """Read and parse at most one bounded legacy HTML file."""

    if notes_path is None or not notes_path.is_file():
        return None
    absolute = notes_path.absolute()
    current = Path(absolute.parts[0])
    for part in absolute.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                raise ContextError("legacy recovery source must not traverse a symlink")
        except OSError as exc:
            raise ContextError("legacy recovery source cannot be inspected") from exc
    raw = notes_path.read_bytes()
    if len(raw) > LEGACY_FALLBACK_MAX_BYTES:
        raise ContextError("legacy recovery source exceeds its bounded read limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContextError("legacy recovery source is not valid UTF-8") from exc
    return _legacy_source_from_text(plan_id, text, parse=parser)


def resolve_context_source(
    *,
    new_resolution: SourceResolution,
    legacy_loader: Callable[[], ContextSource | None] | None = None,
    recovery_boundary: bool = True,
) -> SourceResolution:
    """Apply current-state priority, then invoke one bounded legacy fallback."""

    if new_resolution.source is not None or new_resolution.reason == "ambiguous_active_state":
        return new_resolution
    if not recovery_boundary or legacy_loader is None:
        return new_resolution
    legacy = legacy_loader()
    if legacy is None:
        return new_resolution
    return SourceResolution(legacy, "legacy_fallback", fallback_used=True)


def _fit_lines(lines: Iterable[str], byte_limit: int, word_limit: int) -> str:
    selected: list[str] = []
    for raw_line in lines:
        line = _clean(raw_line, 500)
        if not line:
            continue
        candidate = "\n".join([*selected, line])
        if len(candidate.encode("utf-8")) <= byte_limit and len(candidate.split()) <= word_limit:
            selected.append(line)
            continue
        if not selected:
            words = line.split()
            while words:
                candidate = " ".join(words)
                if len(candidate.encode("utf-8")) <= byte_limit and len(candidate.split()) <= word_limit:
                    selected.append(candidate)
                    break
                words.pop()
    return "\n".join(selected)


def _validation_line(validation: Mapping[str, Any]) -> str:
    pairs = [f"{_clean(key, 80)}={_clean(value, 80)}" for key, value in sorted(validation.items()) if _clean(key, 80) and _clean(value, 80)]
    return ", ".join(pairs)


def _latest_summary(source: ContextSource) -> str:
    event = source.events[-1] if source.events else {}
    return _clean((source.state.get("latest_decision") or {}).get("summary", "") or event.get("summary", ""), 280)


def _capsule_lines(source: ContextSource, kind: str, profile: str, verified: bool) -> tuple[list[str], int, int]:
    state = source.state
    if not verified or profile in {"unknown", "sol"}:
        plan_limit = 23
    elif profile == "terra":
        plan_limit = 64
    elif kind == "delta":
        plan_limit = 48
    else:
        plan_limit = 180
    plan = _clean(source.plan_id, plan_limit)
    status = _clean(state.get("status", ""), 80)
    phase_limit = 32 if profile == "terra" else 48 if kind == "delta" else 120
    phase = _clean(state.get("phase", ""), phase_limit)
    next_action = _clean(state.get("next_action", ""), 280)
    validation = _validation_line(state.get("validation") or {})
    summary = _latest_summary(source)
    blockers = [_clean(item, 180) for item in state.get("open_blockers", []) if _clean(item, 180)]
    questions = [_clean(item, 180) for item in state.get("open_questions", []) if _clean(item, 180)]
    full_authority = "Authority: current user instructions and repository files remain authoritative."
    short_authority = "Authority: user instructions/repo files prevail."
    pointer = ["Progress: " + plan]
    if not verified or profile in {"unknown", "sol"}:
        if status:
            pointer.append("State: " + status)
        pointer.append(short_authority)
        return pointer, POINTER_BYTES, 40
    if status:
        pointer.append("State: " + status + (f"; phase: {phase}" if phase else ""))
    pointer.append(full_authority if profile == "luna" else short_authority)
    if next_action:
        pointer.append("Next: " + next_action)
    if profile == "terra":
        return pointer, TERRA_BYTES, 32
    if kind == "delta":
        lines = ["Implementation progress update", *pointer[:3]]
        if summary:
            lines.append("Changed: " + _clean(summary, 120))
        if next_action:
            lines.append("Next: " + _clean(next_action, 110))
        return lines, LUNA_DELTA_BYTES, LUNA_DELTA_WORDS
    if kind == "expanded":
        lines = ["Implementation progress", *pointer[:3]]
        objective = _clean(state.get("objective", ""), 240)
        if objective:
            lines.append("Objective: " + objective)
        if summary:
            lines.append("Latest decision: " + summary)
        if next_action:
            lines.append("Next: " + next_action)
        if blockers:
            lines.append("Blockers: " + "; ".join(blockers[:3]))
        if questions:
            lines.append("Questions: " + "; ".join(questions[:3]))
        if validation:
            lines.append("Validation: " + validation)
        return lines, LUNA_EXPANDED_BYTES, LUNA_EXPANDED_WORDS
    lines = ["Implementation progress", *pointer[:3]]
    if summary:
        lines.append("Latest decision: " + summary)
    if next_action:
        lines.append("Next: " + next_action)
    if blockers:
        lines.append("Blockers: " + "; ".join(blockers[:3]))
    if validation:
        lines.append("Validation: " + validation)
    generation = state.get("generation", 0)
    if isinstance(generation, int) and generation > 0:
        lines.append(f"Generation: {generation}")
    return lines, LUNA_FULL_BYTES, LUNA_FULL_WORDS


def render_capsule(source: ContextSource, *, kind: str, profile: str = "luna", verified: bool = True) -> str:
    """Render one stable, bounded capsule without paths, hashes, or raw files."""

    if kind not in CAPSULE_KINDS:
        raise ContextError("unsupported capsule kind")
    checked_profile = profile if profile in PROFILES else "unknown"
    lines, byte_limit, word_limit = _capsule_lines(source, kind, checked_profile, verified)
    return _fit_lines(lines, byte_limit, word_limit)


def _capsule_kind(request: ContextRequest) -> str | None:
    if request.event in {"ordinary", "clear", "reset"}:
        return None
    if request.event in {"compact", "startup", "new-session"}:
        return "full"
    if request.event == "explicit":
        return "expanded"
    return "delta" if request.external_writer or request.event == "external" else "full"


def capsule_kind_for(request: ContextRequest) -> str | None:
    """Expose the deterministic kind selection for hook-side ledger probes."""

    return _capsule_kind(request.checked())


def _ledger_record(request: ContextRequest, source: ContextSource, kind: str) -> dict[str, Any]:
    material = {
        "project_id": request.project_id,
        "workspace_instance_id": request.workspace_instance_id,
        "session_id": request.session_id,
        "context_epoch": request.context_epoch,
        "plan_id": source.plan_id,
        "progress_generation": source.generation,
        "capsule_kind": kind,
    }
    emission_id = "ctx-" + hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:40]
    return {"schema_version": 1, **material, "emission_id": emission_id}


def ledger_record_for(request: ContextRequest, source: ContextSource, kind: str) -> dict[str, Any]:
    """Build the content-free emission key without rendering a capsule."""

    if kind not in CAPSULE_KINDS:
        raise ContextError("unsupported capsule kind")
    return _ledger_record(request.checked(), source, kind)


def emit_context(source: ContextSource | None, request: ContextRequest, *, ledger: LedgerLike | None = None) -> ContextDecision:
    """Apply lifecycle rules and claim the ledger only for a real emission."""

    checked = request.checked()
    source_label = source.source if source is not None else "none"
    generation = source.generation if source is not None else 0
    empty = ContextDecision(False, "", "", "no_matching_plan" if source is None else "not_emitted", source_label, False, generation, _source_digest(source) if source else "", _output_digest(""))
    if source is None:
        return empty
    kind = _capsule_kind(checked)
    if kind is None:
        return ContextDecision(False, "", "", "ordinary_or_reset", source.source, False, generation, _source_digest(source), _output_digest(""))
    if checked.session_id == UNKNOWN_SESSION and checked.event not in {"startup", "new-session", "explicit"}:
        return ContextDecision(False, "", kind, "unknown_session", source.source, False, generation, _source_digest(source), _output_digest(""))
    state_writer = _identifier(source.state.get("writer_session_id", ""), "")
    if checked.same_session_write or (state_writer and state_writer == checked.session_id and checked.event not in {"compact", "explicit"}):
        return ContextDecision(False, "", kind, "same_session_writer", source.source, False, generation, _source_digest(source), _output_digest(""))
    capsule = render_capsule(source, kind=kind, profile=checked.profile, verified=checked.verified)
    if not capsule:
        return ContextDecision(False, "", kind, "empty_capsule", source.source, False, generation, _source_digest(source), _output_digest(""))
    if ledger is None:
        return ContextDecision(True, capsule, kind, "emitted_without_ledger", source.source, False, generation, _source_digest(source), _output_digest(capsule))
    claim = ledger.claim_context_emission(_ledger_record(checked, source, kind))
    emitted = bool(getattr(claim, "emitted", getattr(claim, "changed", False)))
    reason = "emitted" if emitted else "ledger_hit"
    return ContextDecision(emitted, capsule if emitted else "", kind, reason, source.source, not emitted, generation, _source_digest(source), _output_digest(capsule if emitted else ""))


__all__ = [
    "ACTIVE_STATUSES",
    "CAPSULE_KINDS",
    "CONTEXT_EVENTS",
    "ContextDecision",
    "ContextError",
    "ContextRequest",
    "ContextSource",
    "SourceResolution",
    "capsule_kind_for",
    "derive_context_epoch",
    "emit_context",
    "ledger_record_for",
    "legacy_fallback",
    "render_capsule",
    "resolve_context_source",
    "select_new_state_source",
]
