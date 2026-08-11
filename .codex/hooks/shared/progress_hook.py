"""Hook-local bridge to the deterministic implementation-progress engine.

The bridge deliberately separates a cheap identity read from a miss-only
history read.  It is safe to call from both lifecycle dispatchers: no store
layout is created by lookup and the local path resolver never invokes Git.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .active_context import ActiveContext, local_git_identity
from .implementation_store import FutureSchemaError, ImplementationStore, StorePathError, resolve_store_paths_local
from .runtime_profile import RuntimeProfile


def _engine_roots() -> tuple[Path, ...]:
    """Resolve the canonical pure engine for local and globally copied hooks.

    Global hook installation copies the hook tree but records the canonical
    checkout in ``.ralph-repo-root``.  Reading that marker keeps this bridge
    pointed at one implementation without copying the engine into the global
    hook tree or invoking Git/another child process on the hot path.
    """

    hook_dir = Path(__file__).resolve().parents[1]
    roots: list[Path] = [Path(__file__).resolve().parents[3]]
    marker = hook_dir / ".ralph-repo-root"
    try:
        if marker.is_file():
            value = marker.read_text(encoding="utf-8").strip()
            if value:
                roots.append(Path(value).expanduser())
    except OSError:
        pass
    result: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved not in result:
            result.append(resolved)
    return tuple(result)


for _engine_root in _engine_roots():
    _plans_dir = _engine_root / "scripts" / "plans"
    _security_dir = _engine_root / "scripts" / "security"
    if str(_plans_dir) not in sys.path:
        sys.path.insert(0, str(_plans_dir))
    if str(_security_dir) not in sys.path:
        sys.path.insert(0, str(_security_dir))

from progress_context import (  # noqa: E402
    ContextDecision,
    ContextRequest,
    ContextSource,
    SourceResolution,
    capsule_kind_for,
    derive_context_epoch,
    emit_context,
    legacy_fallback,
    ledger_record_for,
    resolve_context_source,
    select_new_state_source,
)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")
_EXPLICIT_PROGRESS_RE = re.compile(
    r"\b(?:implementation\s+progress|progress\s+context|progress\s+recovery|where\s+are\s+we|what(?:'s| is)\s+the\s+current\s+phase)\b",
    re.IGNORECASE,
)
_PROFILE_NAMES = frozenset({"luna", "terra", "sol", "unknown"})
_DISCOVERABLE_STATUSES = frozenset({"active", "reopened"})


@dataclass(frozen=True)
class ProgressIdentity:
    plan_id: str
    generation: int
    status: str
    writer_session_id: str
    plan_path: str
    reason: str
    source: str = "state"
    semantic_hash: str = ""


@dataclass(frozen=True)
class ProgressLookup:
    store: ImplementationStore | None
    identity: ProgressIdentity | None
    resolution: SourceResolution

    @property
    def available(self) -> bool:
        return self.store is not None and self.identity is not None

    @property
    def context_identity(self) -> str:
        if not self.identity:
            return "none"
        return f"{self.identity.plan_id}:{self.identity.generation}:{self.identity.status}"


def _safe_identifier(value: object, default: str) -> str:
    text = str(value or "").strip()
    return text if _IDENTIFIER_RE.fullmatch(text) else default


def _root_candidates(context: ActiveContext, payload: Mapping[str, object]) -> tuple[Path, ...]:
    values: list[object] = []
    for key in (
        "primary_repo_root",
        "primaryRoot",
        "canonical_repo_root",
        "canonicalRepoRoot",
        "implementation_store_root",
    ):
        values.append(payload.get(key))
    configured = os.environ.get("RALPH_PROGRESS_PRIMARY_ROOT", "").strip()
    if configured:
        values.append(configured)
    values.extend((context.workspace_root, Path(__file__).resolve().parents[3]))
    result: list[Path] = []
    explicit_primary_keys = {
        "primary_repo_root",
        "primaryRoot",
        "canonical_repo_root",
        "canonicalRepoRoot",
        "implementation_store_root",
    }
    for index, value in enumerate(values):
        if not isinstance(value, (str, Path)) or not str(value).strip():
            continue
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.exists() or not path.is_dir():
            continue
        try:
            resolved = path.absolute()
        except OSError:
            continue
        detached_primary = (
            not context.workspace_root.exists()
            and index < len(explicit_primary_keys)
            and isinstance(value, (str, Path))
        )
        if not _candidate_is_canonical(context, resolved, allow_detached_primary=detached_primary):
            continue
        if resolved not in result:
            result.append(resolved)
    return tuple(result)


def _candidate_is_canonical(
    context: ActiveContext,
    candidate: Path,
    *,
    allow_detached_primary: bool = False,
) -> bool:
    """Keep hook-local store selection inside the active Git identity.

    The fast path cannot invoke Git, but it can still inspect the local
    ``.git`` pointer and common directory.  A candidate must be the main
    checkout for the same repository as the active worktree.  Non-Git fixture
    roots remain valid only when they are the active workspace itself.
    """

    active_root = context.workspace_root
    active_identity = local_git_identity(active_root)
    candidate_identity = local_git_identity(candidate)
    if active_identity is None and allow_detached_primary:
        # A deleted linked worktree cannot provide a local ``.git`` identity.
        # An explicit primary checkout is still safe to inspect because it is
        # independently proven to be a real main checkout; completion later
        # applies the workspace/branch/HEAD gates before any mutation.
        if candidate_identity is None:
            return False
        candidate_top, candidate_git, candidate_common = candidate_identity
        return candidate_top == candidate and candidate_git == candidate_common
    if active_identity is None:
        return candidate == active_root.absolute()
    if candidate_identity is None:
        return False
    active_common = active_identity[2]
    candidate_top, candidate_git, candidate_common = candidate_identity
    return candidate_common == active_common and candidate_git == candidate_common and candidate_top == candidate


def local_store(context: ActiveContext, payload: Mapping[str, object]) -> ImplementationStore | None:
    """Find an existing local store without resolving Git or creating files."""

    for root in _root_candidates(context, payload):
        try:
            paths = resolve_store_paths_local(root)
        except (StorePathError, OSError, ValueError):
            continue
        if paths.manifest.exists() or paths.root.exists():
            return ImplementationStore(paths)
    return None


def _workspace_matches(pointer: Mapping[str, object], workspace_instance_id: str) -> bool:
    pointer_workspace = str(pointer.get("workspace_instance_id") or "").strip()
    return not pointer_workspace or pointer_workspace in {workspace_instance_id, f"ws-{workspace_instance_id}"}


def _legacy_enabled() -> bool:
    return os.environ.get("RALPH_PROGRESS_LEGACY_FALLBACK", "").strip().lower() in {"1", "true", "yes"}


def cheap_lookup(context: ActiveContext, payload: Mapping[str, object]) -> ProgressLookup:
    """Read manifest and state identity only; never read the event journal."""

    store = local_store(context, payload)
    if store is None:
        explicit_plan = payload.get("progress_plan_id") or payload.get("progressPlanId")
        explicit_root = any(
            isinstance(payload.get(key), (str, Path)) and str(payload.get(key)).strip()
            for key in (
                "primary_repo_root",
                "primaryRoot",
                "canonical_repo_root",
                "canonicalRepoRoot",
                "implementation_store_root",
            )
        )
        # An explicitly requested plan with an untrusted root is a safety
        # failure, not an ordinary cache miss.  No foreign store is opened,
        # but Stop can still fail closed with a typed integrity finding.
        reason = "state_invalid" if explicit_plan and explicit_root else "state_unavailable"
        return ProgressLookup(None, None, SourceResolution(None, reason))
    try:
        manifest = store.read_manifest()
    except FutureSchemaError:
        return ProgressLookup(store, None, SourceResolution(None, "future_schema"))
    except Exception:
        return ProgressLookup(store, None, SourceResolution(None, "state_invalid"))
    if not manifest:
        return ProgressLookup(store, None, SourceResolution(None, "state_unavailable"))

    expected_workspace = _safe_identifier(
        payload.get("workspace_instance_id") or payload.get("workspaceInstanceId") or context.workspace_instance_id,
        context.workspace_instance_id,
    )
    explicit_plan = payload.get("progress_plan_id") or payload.get("progressPlanId")
    pointers = manifest.get("plans", [])
    if explicit_plan:
        candidates = [
            {"plan_id": str(explicit_plan), "status": "active", "plan_path": ""}
        ]
    else:
        candidates = [
            pointer
            for pointer in pointers
            if isinstance(pointer, Mapping)
            and pointer.get("status") in _DISCOVERABLE_STATUSES
            and _workspace_matches(pointer, expected_workspace)
        ]
    identities: list[ProgressIdentity] = []
    invalid_state = False
    future_schema = False
    for pointer in candidates:
        plan_id = str(pointer.get("plan_id") or "")
        if not plan_id:
            continue
        try:
            state = store.read_state_identity(plan_id)
        except FutureSchemaError:
            future_schema = True
            continue
        except Exception:
            invalid_state = True
            continue
        if not state or state.get("status") not in _DISCOVERABLE_STATUSES:
            continue
        # An unqualified lifecycle event must not inherit an active plan from
        # another branch or HEAD merely because the canonical checkout is
        # discoverable.  Explicit plan references remain available so the
        # completion path can emit its stronger identity-mismatch gate.
        if not explicit_plan and not _payload_provenance_matches(state, payload):
            continue
        identities.append(
            ProgressIdentity(
                plan_id=plan_id,
                generation=int(state.get("generation", 0) or 0),
                status=str(state.get("status") or ""),
                writer_session_id=str(state.get("writer_session_id") or ""),
                plan_path=str(pointer.get("plan_path") or state.get("plan_path") or ""),
                reason="explicit_state" if explicit_plan else "single_active_state",
                semantic_hash=str(state.get("semantic_hash") or ""),
            )
        )
    if len(identities) == 1:
        identity = identities[0]
        return ProgressLookup(store, identity, SourceResolution(None, identity.reason))
    if len(identities) > 1:
        return ProgressLookup(store, None, SourceResolution(None, "ambiguous_active_state"))
    if future_schema:
        return ProgressLookup(store, None, SourceResolution(None, "future_schema"))
    if invalid_state:
        return ProgressLookup(store, None, SourceResolution(None, "state_invalid"))
    if _legacy_enabled() and len(candidates) == 1:
        pointer = candidates[0]
        plan_id = str(pointer.get("plan_id") or "")
        if plan_id:
            identity = ProgressIdentity(
                plan_id=plan_id,
                generation=0,
                status="legacy",
                writer_session_id="",
                plan_path=str(pointer.get("plan_path") or ""),
                reason="legacy_candidate",
                source="legacy",
            )
            return ProgressLookup(store, identity, SourceResolution(None, "legacy_candidate"))
    return ProgressLookup(store, None, SourceResolution(None, "no_active_state"))


def _payload_provenance_matches(state: Mapping[str, object], payload: Mapping[str, object]) -> bool:
    value = state.get("git")
    git = value if isinstance(value, Mapping) else {}
    supplied_branch = str(payload.get("branch") or payload.get("git_branch") or "").strip()
    recorded_branch = str(git.get("branch") or "").strip()
    if supplied_branch and recorded_branch and supplied_branch != recorded_branch:
        return False
    supplied_sha = str(payload.get("sha") or payload.get("git_sha") or "").strip()
    recorded_sha = str(git.get("commit") or git.get("sha") or "").strip()
    if supplied_sha and recorded_sha and not (supplied_sha.startswith(recorded_sha) or recorded_sha.startswith(supplied_sha)):
        return False
    return True


def source_for_lookup(lookup: ProgressLookup) -> ContextSource | None:
    if not lookup.available or lookup.store is None or lookup.identity is None:
        return None
    try:
        state = lookup.store.read_state(lookup.identity.plan_id)
        if state is None:
            return None
        events = tuple(lookup.store.read_events(lookup.identity.plan_id))
    except Exception:
        return None
    return ContextSource(plan_id=lookup.identity.plan_id, state=state, events=events, source="state")


def _legacy_source(lookup: ProgressLookup) -> ContextSource | None:
    if lookup.store is None or lookup.identity is None:
        return None
    if os.environ.get("RALPH_PROGRESS_LEGACY_FALLBACK", "").strip().lower() not in {"1", "true", "yes"}:
        return None
    plan_path = lookup.identity.plan_path
    if not plan_path:
        return None
    plan = lookup.store.paths.primary_root / plan_path
    notes = plan.with_name(f"{plan.stem}-implementation-notes.html")
    return legacy_fallback(plan_id=lookup.identity.plan_id, notes_path=notes)


def recovery_source(lookup: ProgressLookup, *, recovery_boundary: bool) -> SourceResolution:
    """Load full state/journal only on a recovery/render miss."""

    if lookup.identity is not None:
        source = source_for_lookup(lookup)
        if source is not None:
            return SourceResolution(source, lookup.identity.reason)
    if lookup.resolution.reason == "ambiguous_active_state":
        return lookup.resolution
    return resolve_context_source(
        new_resolution=lookup.resolution,
        legacy_loader=lambda: _legacy_source(lookup),
        recovery_boundary=recovery_boundary,
    )


def progress_event_for_prompt(prompt: str, payload: Mapping[str, object]) -> str:
    explicit = payload.get("progress_request") or payload.get("progressRequest") or payload.get("context_request")
    if isinstance(explicit, bool) and explicit:
        return "explicit"
    if isinstance(explicit, str) and explicit.strip().lower() in {"1", "true", "yes", "progress", "context"}:
        return "explicit"
    return "explicit" if _EXPLICIT_PROGRESS_RE.search(prompt) else "ordinary"


def context_epoch(payload: Mapping[str, object], event: str, session_id: str) -> str:
    supplied = payload.get("context_epoch") or payload.get("contextEpoch")
    if isinstance(supplied, str) and supplied.strip():
        return _safe_identifier(supplied, derive_context_epoch(None, event, session_id))
    previous = payload.get("previous_context_epoch") or payload.get("previousContextEpoch")
    previous_text = previous if isinstance(previous, str) else None
    return derive_context_epoch(previous_text, event, session_id)


def request_for(
    profile: RuntimeProfile,
    context: ActiveContext,
    payload: Mapping[str, object],
    *,
    event: str,
    external_writer: bool = False,
    same_session_write: bool = False,
) -> ContextRequest:
    model_profile = profile.model_family if profile.model_family in _PROFILE_NAMES else "unknown"
    return ContextRequest(
        profile=model_profile,
        verified=profile.model_verified,
        # Project and worktree identity are derived from the active context;
        # hook payload fields cannot forge a ledger scope or replay another
        # worktree's capsule.
        project_id=context.project_id,
        workspace_instance_id=context.workspace_instance_id,
        session_id=_safe_identifier(context.session_id, "unknown"),
        context_epoch=context_epoch(payload, event, context.session_id),
        event=event,
        external_writer=external_writer,
        same_session_write=same_session_write,
    )


def ledger_key_record(lookup: ProgressLookup, request: ContextRequest) -> dict[str, Any] | None:
    if lookup.identity is None:
        return None
    source = ContextSource(
        plan_id=lookup.identity.plan_id,
        state={"generation": lookup.identity.generation},
        source=lookup.identity.source,
    )
    kind = capsule_kind_for(request)
    return ledger_record_for(request, source, kind) if kind else None


def emit_lookup(lookup: ProgressLookup, request: ContextRequest, *, recovery_boundary: bool) -> Any:
    if lookup.store is None:
        return emit_context(None, request)
    record = ledger_key_record(lookup, request)
    if record is not None:
        try:
            if lookup.store.has_context_emission(record):
                kind = capsule_kind_for(request)
                return ContextDecision(
                    emitted=False,
                    capsule="",
                    capsule_kind=kind or "",
                    reason="ledger_hit",
                    source=lookup.identity.source if lookup.identity else "state",
                    ledger_hit=True,
                    progress_generation=lookup.identity.generation if lookup.identity else 0,
                    source_digest="",
                    output_digest="sha256:" + hashlib.sha256(b"").hexdigest(),
                )
        except Exception:
            return emit_context(None, request)
    source_resolution = recovery_source(lookup, recovery_boundary=recovery_boundary)
    return emit_context(source_resolution.source, request, ledger=lookup.store)


def identity_marker(lookup: ProgressLookup) -> str:
    raw = lookup.context_identity
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "ProgressIdentity",
    "ProgressLookup",
    "cheap_lookup",
    "context_epoch",
    "emit_lookup",
    "identity_marker",
    "ledger_key_record",
    "local_store",
    "progress_event_for_prompt",
    "recovery_source",
    "request_for",
    "source_for_lookup",
]
