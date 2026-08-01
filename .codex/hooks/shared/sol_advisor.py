"""Bounded state for the native GPT-5.6 Sol advisor lane."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import tomllib
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Iterator

from .redaction import is_red
from .subagent_routing import (
    LUNA_DEFAULT_EFFORT,
    LUNA_MODEL,
    SOL_MODEL as ROUTING_SOL_MODEL,
    ExecutorDefaults,
    RoutingBudget,
    RoutingCapabilities,
    RoutingRequest,
    SubagentOverride,
    resolve_subagent_routing,
)
from .tool_result import success_from_payload

STATE_FILE = "sol-advisor.json"
STATE_VERSION = 2
MAX_FAILURE_FINGERPRINTS = 4
MAX_CONSULTATIONS = 2
CONSULTATION_PHASES = frozenset({"plan", "stuck", "final"})
HIGH_IMPACT_RE = re.compile(
    r"\b(architecture|authorization|auth|schema|database|migration|rollout|deploy|"
    r"public api|external interface|breaking|security|compliance|contract)\b",
    re.IGNORECASE,
)
EXPLICIT_RE = re.compile(r"\b(sol[ -]?advisor|consult(?:ar)?\s+(?:a\s+)?sol)\b", re.IGNORECASE)
CONTINUATION_RE = re.compile(r"^\s*(continue|continua|sigue|resume|where were we)\b", re.IGNORECASE)
SOL_MODEL = ROUTING_SOL_MODEL
SENSITIVITY_RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2}


def state_path(payload: dict[str, Any]) -> Path:
    configured_root = os.environ.get("CODEX_HOOK_STATE_ROOT", "").strip()
    if configured_root:
        root = Path(configured_root).expanduser()
    else:
        cwd = payload.get("cwd")
        base = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
        root = base / ".codex" / "state"
    return root / safe_session_id(payload.get("session_id") or payload.get("sessionId")) / STATE_FILE


def safe_session_id(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "unknown"))[:80].strip("_")
    return cleaned or "unknown"


def read_state(payload: dict[str, Any]) -> dict[str, Any]:
    path = state_path(payload)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@contextmanager
def locked_state(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    path = state_path(payload)
    lock_path = path.with_suffix(".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                state = read_state(payload)
                yield state
                try:
                    atomic_write(path, state)
                except OSError:
                    pass
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Operational state is advisory. A local filesystem problem must not
        # interrupt the executor or force a second attempt at the same action.
        yield {}


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def classification_complexity(payload: dict[str, Any]) -> int:
    path = state_path(payload).with_name("prompt-classification.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("complexity", 1)
        return max(1, min(10, int(value)))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        value = payload.get("complexity", 1)
        try:
            return max(1, min(10, int(value)))
        except (ValueError, TypeError):
            return 1


def _bounded_text(value: object, *, limit: int = 80) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _payload_value(payload: dict[str, Any], *keys: str) -> object:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    for container_key in ("task_intake", "taskIntake", "routing", "route"):
        container = payload.get(container_key)
        if isinstance(container, dict):
            for key in keys:
                value = container.get(key)
                if value is not None:
                    return value
    return None


def _parse_bool(value: object) -> bool | None:
    """Decode structured boolean evidence without treating ``"false"`` as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


ROUTING_EVIDENCE: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("spawn_model_effort_available", ("spawn_model_effort_available", "spawnModelEffortAvailable"), True),
    ("active_analysis_enabled", ("active_analysis_enabled", "activeAnalysisEnabled"), False),
    ("bounded_scope", ("bounded_scope", "boundedScope"), False),
    ("local_verification_available", ("local_verification_available", "localVerificationAvailable"), False),
    ("hard_gates_pass", ("hard_gates_pass", "hardGatesPass"), True),
)


def _capture_routing_evidence(state: dict[str, Any], payload: dict[str, Any]) -> None:
    """Persist only bounded gate evidence needed to make continuations deterministic."""
    for state_key, payload_keys, default in ROUTING_EVIDENCE:
        value = _payload_value(payload, *payload_keys)
        if value is not None:
            parsed = _parse_bool(value)
            # A failed hard gate is sticky for the current task. Only the
            # explicit task-boundary branch creates a fresh state that can
            # establish a new gate result; an omitted or malformed
            # continuation value must never restore active analysis.
            if state_key == "hard_gates_pass" and state.get(state_key) is False and not is_task_boundary(payload, ""):
                state[state_key] = False
            else:
                state[state_key] = parsed if parsed is not None else False
    budget_value = _payload_value(payload, "budget_class", "budgetClass")
    if budget_value is not None:
        state["budget_class"] = _bounded_text(budget_value, limit=32) or None


def _routing_bool(
    state: dict[str, Any], payload: dict[str, Any], state_key: str, payload_keys: tuple[str, ...], default: bool
) -> bool:
    value = _payload_value(payload, *payload_keys)
    if value is None:
        value = state.get(state_key, default)
        parsed = _parse_bool(value)
        return parsed if parsed is not None else default
    parsed = _parse_bool(value)
    # Explicit malformed gate evidence fails closed. In particular, a bogus
    # hard_gates_pass value cannot reactivate a previously rejected route.
    return parsed if parsed is not None else False


def _normalize_phase_reservations(state: dict[str, Any]) -> dict[str, dict[str, object]]:
    """Keep short-lived, bounded reservations for an about-to-start Sol spawn."""
    raw = state.get("phase_reservations")
    if not isinstance(raw, dict):
        state["phase_reservations"] = {}
        return {}
    now = int(time.time())
    normalized: dict[str, dict[str, object]] = {}
    for phase, value in raw.items():
        if not isinstance(value, dict):
            continue
        normalized_phase = normalize_phase(phase)
        fingerprint = _bounded_text(value.get("fingerprint"), limit=64)
        try:
            reserved_at = int(value.get("reserved_at", 0) or 0)
        except (TypeError, ValueError):
            continue
        # Reservations are released only by the matching start/failure or a
        # fresh task state. Never expire a live queued spawn by wall clock.
        if not normalized_phase or not fingerprint or reserved_at > now + 120:
            continue
        record: dict[str, object] = {"fingerprint": fingerprint, "reserved_at": reserved_at}
        spawn_shape = _bounded_text(value.get("spawn_shape"), limit=64)
        invocation_id = _bounded_text(value.get("invocation_id"), limit=80)
        if spawn_shape:
            record["spawn_shape"] = spawn_shape
        if invocation_id:
            record["invocation_id"] = invocation_id
        normalized[normalized_phase] = record
    state["phase_reservations"] = normalized
    return normalized


def _state_budget_remaining(state: dict[str, Any]) -> int:
    try:
        budget = int(state["consultation_budget"])
        count = int(state["consultation_count"])
        stored = int(state["budget_remaining"])
    except (KeyError, TypeError, ValueError):
        return 0
    if budget < 0 or count < 0 or stored < 0 or count > budget:
        return 0
    return max(0, min(stored, budget - count))


def _spawn_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [payload]
    for key in ("tool_input", "toolInput", "input", "subagent", "agent"):
        value = payload.get(key)
        if isinstance(value, dict):
            sources.append(value)
    return sources


def _spawn_metadata(payload: dict[str, Any]) -> tuple[str, str]:
    """Return stable spawn shape and optional exact invocation identity."""
    invocation_keys = ("tool_call_id", "toolCallId", "call_id", "callId", "invocation_id", "invocationId")
    invocation_id = ""
    for source in _spawn_sources(payload):
        for key in invocation_keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                invocation_id = _bounded_text(value, limit=80)
                break
        if invocation_id:
            break
    shape_values: list[str] = []
    for source in _spawn_sources(payload):
        for key in (
            "agent_type",
            "agentType",
            "task_name",
            "taskName",
            "model",
            "model_name",
            "modelName",
            "reasoning_effort",
            "reasoningEffort",
            "effort",
            "subagent_route",
            "subagentRoute",
        ):
            value = source.get(key)
            if value is not None and str(value).strip():
                shape_values.append(f"{key}={_bounded_text(value, limit=80)}")
    shape = _hash_material("spawn-shape", *shape_values) if shape_values else ""
    return shape, invocation_id


def reserve_sol_consultation(payload: dict[str, Any], phase: str, fingerprint: str) -> tuple[bool, str]:
    """Atomically reserve one Sol phase without consuming budget before start."""
    normalized_phase = normalize_phase(phase)
    if not normalized_phase or not fingerprint:
        return False, "Sol consultation reservation lacks a valid phase or decision fingerprint."
    with locked_state(payload) as state:
        ensure_state_shape(state, payload)
        if not isinstance(state.get("routing"), dict):
            return False, "Subagent routing state is unavailable; the spawn was blocked for safety."
        reservations = _normalize_phase_reservations(state)
        consulted_phases = state.get("consulted_phases")
        if isinstance(consulted_phases, dict) and consulted_phases.get(normalized_phase):
            return False, "A Sol consultation has already been started for this lifecycle phase."
        if normalized_phase in reservations:
            return False, "A Sol consultation is already reserved for this lifecycle phase."
        if _state_budget_remaining(state) <= 0:
            return False, "Sol consultation budget is exhausted; do not create another advisor spawn."
        spawn_shape, invocation_id = _spawn_metadata(payload)
        if not spawn_shape and not invocation_id:
            return False, "Sol consultation reservation lacks a bounded spawn identity."
        reservations[normalized_phase] = {
            "fingerprint": _bounded_text(fingerprint, limit=64),
            "reserved_at": int(time.time()),
            "spawn_shape": spawn_shape,
            "invocation_id": invocation_id,
        }
        state["phase_reservations"] = reservations
        return True, ""


def reserved_phase_for_start(state: dict[str, Any], payload: dict[str, Any]) -> str:
    """Resolve a SubagentStart to its persisted reservation, never its phase field."""
    reservations = _normalize_phase_reservations(state)
    if not reservations:
        return ""
    routing = state.get("routing")
    fingerprint = str(routing.get("decision_fingerprint") or "") if isinstance(routing, dict) else ""
    if not fingerprint:
        return ""
    shape, invocation_id = _spawn_metadata(payload)
    matches: list[str] = []
    for phase, reservation in reservations.items():
        if str(reservation.get("fingerprint") or "") != fingerprint:
            continue
        recorded_shape = _bounded_text(reservation.get("spawn_shape"), limit=64)
        recorded_invocation = _bounded_text(reservation.get("invocation_id"), limit=80)
        identity_match = bool(
            recorded_invocation
            and invocation_id
            and recorded_invocation == invocation_id
        )
        shape_match = bool(recorded_shape and shape and recorded_shape == shape)
        if identity_match or shape_match:
            matches.append(phase)
    return matches[0] if len(matches) == 1 else ""


def _infer_intent(prompt: str, payload: dict[str, Any]) -> str:
    explicit = _bounded_text(_payload_value(payload, "intent", "task_type", "taskType"), limit=48)
    if explicit:
        return explicit.lower().replace("_", "-")
    lowered = prompt.lower()
    if re.search(r"\b(security|vulnerability|compliance|threat model|secreto|credencial)\b", lowered):
        return "security"
    if re.search(r"\b(migration|migrate|migración|migracion|rollout|deploy|despliegue)\b", lowered):
        return "migration"
    if re.search(r"\b(debug|debugging|diagnos|failure|failing|broken|error|fallo|avería|averia)\b", lowered):
        return "debugging"
    if re.search(r"\b(architecture|architectural|arquitectura|design|diseño|diseno)\b", lowered):
        return "architecture"
    if re.search(r"\b(implement|implementation|fix|patch|build|create|modify|change|add|refactor|implementar|corregir|construir|crear|modificar|cambiar|agregar|refactorizar)\b", lowered):
        return "implementation"
    return "routine"


def _sensitivity(prompt: str, payload: dict[str, Any]) -> str:
    values: list[str] = []
    sources = [payload]
    for key in ("task_intake", "taskIntake", "routing", "route"):
        source = payload.get(key)
        if isinstance(source, dict):
            sources.append(source)
    for source in sources:
        for key in ("sensitivity", "classification"):
            explicit = _bounded_text(source.get(key), limit=16).upper()
            if explicit in SENSITIVITY_RANK:
                values.append(explicit)
    explicit = max(values, key=lambda value: SENSITIVITY_RANK[value]) if values else "GREEN"
    if explicit in SENSITIVITY_RANK:
        return "RED" if explicit == "RED" or is_red(prompt) else explicit
    return "RED" if is_red(prompt) else "GREEN"


def _override(value: object) -> SubagentOverride | None:
    if not isinstance(value, dict):
        return None
    model = _bounded_text(value.get("model"), limit=64) or None
    effort = _bounded_text(value.get("reasoning_effort", value.get("effort")), limit=16) or None
    route = _bounded_text(value.get("route"), limit=48) or None
    expiry_value = value.get("expires_at", value.get("expiresAt"))
    try:
        expiry = int(expiry_value) if expiry_value is not None else None
    except (TypeError, ValueError):
        expiry = None
    if not any((model, effort, route)) and expiry is None:
        return None
    return SubagentOverride(model=model, reasoning_effort=effort, route=route, expires_at=expiry)


def _override_record(value: object) -> dict[str, object] | None:
    """Persist only the bounded, validated fields of an override."""
    candidate = value if isinstance(value, SubagentOverride) else _override(value)
    if candidate is None:
        return None
    record: dict[str, object] = {}
    for key, field in (
        ("model", candidate.model),
        ("reasoning_effort", candidate.reasoning_effort),
        ("route", candidate.route),
        ("expires_at", candidate.expires_at),
    ):
        if field is not None:
            record[key] = field
    return record


def _capture_payload_overrides(state: dict[str, Any], payload: dict[str, Any]) -> None:
    """Remember scoped overrides so ordinary continuation payloads may omit them."""
    for state_key, payload_keys in (
        ("task_subagent_override", ("task_subagent_override", "taskSubagentOverride")),
        ("session_subagent_override", ("session_subagent_override", "sessionSubagentOverride")),
    ):
        value = _payload_value(payload, *payload_keys)
        if value is not None:
            state[state_key] = _override_record(value)


def _configured_executor_defaults(payload: dict[str, Any]) -> tuple[ExecutorDefaults, str]:
    """Read the immutable executor default; hooks never write this file."""
    cwd_value = payload.get("cwd")
    cwd = Path(cwd_value) if isinstance(cwd_value, str) and cwd_value else Path.cwd()
    candidates: list[tuple[Path, str]] = []
    repository_bases = [cwd]
    try:
        repository_bases.append(Path(os.path.realpath(cwd)))
    except (OSError, TypeError):
        pass
    for base in repository_bases:
        current = base
        while True:
            candidates.append((current / ".codex" / "config.toml", "repository"))
            if (current / ".git").exists() or current.parent == current:
                break
            current = current.parent
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    candidates.append((codex_home / "config.toml", "global"))
    seen: set[Path] = set()
    for candidate, source in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            config = tomllib.loads(candidate.read_text(encoding="utf-8"))
            model = _bounded_text(config.get("model"), limit=64)
            effort = _bounded_text(config.get("model_reasoning_effort"), limit=16)
            if model and effort:
                return ExecutorDefaults(model, effort), source
        # ``tomllib`` is provided by the runtime on newer Python versions and
        # by this repository's compatibility parser on older ones.  Both
        # surface malformed input as a ValueError-family failure, but the
        # compatibility parser does not expose TOMLDecodeError by name.
        except (OSError, ValueError, TypeError):
            continue
    return ExecutorDefaults(LUNA_MODEL, LUNA_DEFAULT_EFFORT), "fallback"


def _routing_decision(
    state: dict[str, Any], payload: dict[str, Any], prompt: str, *, explicit_request: bool
) -> dict[str, Any]:
    raw_complexity = max(1, min(10, int(state.get("complexity", 1) or 1)))
    intent = _infer_intent(prompt, payload)
    if intent == "routine" and str(state.get("intent", "routine")) != "routine":
        # A short continuation such as "status update" must not erase the
        # active task's previously classified lane.
        intent = str(state.get("intent"))
    sensitivity = _sensitivity(prompt, payload)
    previous_sensitivity = str(state.get("sensitivity", "GREEN")).upper()
    previous_routing = state.get("routing")
    if isinstance(previous_routing, dict):
        routing_sensitivity = str(previous_routing.get("sensitivity", "GREEN")).upper()
        if SENSITIVITY_RANK.get(routing_sensitivity, 0) > SENSITIVITY_RANK.get(previous_sensitivity, 0):
            previous_sensitivity = routing_sensitivity
    if (
        not is_task_boundary(payload, prompt)
        and SENSITIVITY_RANK.get(previous_sensitivity, 0) > SENSITIVITY_RANK.get(sensitivity, 0)
    ):
        # A continuation must not downgrade an already classified task merely
        # because its short follow-up text contains fewer sensitivity signals.
        sensitivity = previous_sensitivity
    impact_class = "material" if state.get("high_impact") else "none"
    task_value = _payload_value(payload, "task_subagent_override", "taskSubagentOverride")
    session_value = _payload_value(payload, "session_subagent_override", "sessionSubagentOverride")
    task_override = _override(task_value) if task_value is not None else _override(state.get("task_subagent_override"))
    session_override = (
        _override(session_value) if session_value is not None else _override(state.get("session_subagent_override"))
    )
    if explicit_request and task_override is None:
        task_override = SubagentOverride(model=SOL_MODEL, route="sol-advisor")
    existing_routing = state.get("routing")
    if isinstance(existing_routing, dict):
        try:
            remaining = max(0, int(state.get("budget_remaining", 0) or 0))
        except (TypeError, ValueError):
            remaining = 0
    else:
        remaining = MAX_CONSULTATIONS
    capabilities = RoutingCapabilities(
        spawn_model_effort=_routing_bool(
            state,
            payload,
            "spawn_model_effort_available",
            ("spawn_model_effort_available", "spawnModelEffortAvailable"),
            True,
        ),
        active_analysis=_routing_bool(
            state,
            payload,
            "active_analysis_enabled",
            ("active_analysis_enabled", "activeAnalysisEnabled"),
            False,
        ),
    )
    budget_class_value = _payload_value(payload, "budget_class", "budgetClass")
    if budget_class_value is None:
        budget_class_value = state.get("budget_class")
    budget = RoutingBudget(
        remaining=remaining,
        explicit_class=_bounded_text(budget_class_value, limit=32) or None,
    )
    current_epoch_value = _payload_value(payload, "current_epoch", "currentEpoch")
    try:
        current_epoch = int(time.time()) if current_epoch_value is None else int(current_epoch_value)
    except (TypeError, ValueError):
        current_epoch = int(time.time())
    executor_defaults, executor_source = _configured_executor_defaults(payload)
    decision = resolve_subagent_routing(
        RoutingRequest(
            raw_complexity=raw_complexity,
            intent=intent,
            impact_class=impact_class,
            sensitivity=sensitivity,
            # A repository config is authoritative when present.  In a
            # neutral workspace the Luna/max fallback belongs to the global
            # default lane; preserving that distinction keeps the routing
            # metadata truthful for callers and diagnostics.
            repository_default=executor_defaults if executor_source == "repository" else None,
            global_default=(
                executor_defaults
                if executor_source != "repository"
                else ExecutorDefaults(LUNA_MODEL, LUNA_DEFAULT_EFFORT)
            ),
            task_override=task_override,
            session_override=session_override,
            current_epoch=current_epoch,
            capabilities=capabilities,
            budget=budget,
            bounded_scope=_routing_bool(
                state, payload, "bounded_scope", ("bounded_scope", "boundedScope"), False
            ),
            local_verification_available=_routing_bool(
                state,
                payload,
                "local_verification_available",
                ("local_verification_available", "localVerificationAvailable"),
                False,
            ),
            hard_gates_pass=_routing_bool(
                state, payload, "hard_gates_pass", ("hard_gates_pass", "hardGatesPass"), True
            ),
        )
    )
    serialized = {
        "policy_version": decision.policy_version,
        "raw_complexity": decision.raw_complexity,
        "effective_complexity": decision.effective_complexity,
        "intent": decision.intent,
        "impact_class": decision.impact_class,
        "sensitivity": decision.sensitivity,
        "configured_executor_model": decision.configured_executor_model,
        "configured_executor_effort": decision.configured_executor_effort,
        "configured_executor_source": decision.configured_executor_source,
        "subagent_route": decision.subagent_route,
        "subagent_model": decision.subagent_model,
        "subagent_mode": decision.subagent_mode,
        "subagent_effort": decision.subagent_effort,
        "spawn_required": decision.spawn_required,
        "spawn_arguments": dict(decision.spawn_arguments),
        "active_analysis_eligible": decision.active_analysis_eligible,
        "active_analysis_rejection_reason": decision.active_analysis_rejection_reason,
        "override_scope": decision.override_scope,
        "override_requested": dict(decision.override_requested),
        "override_effective": dict(decision.override_effective),
        "override_rejection_reason": decision.override_rejection_reason,
        "override_rejections": dict(decision.override_rejections),
        "override_expiry": decision.override_expiry,
        "budget_remaining": decision.budget_remaining,
        "decision_fingerprint": decision.decision_fingerprint,
        "reason_code": decision.reason_code,
    }
    # The resolver has only repository/global lanes; retain the loader's
    # explicit fallback label so the hook can distinguish a real repo config
    # from the safe Luna/max default used when no config is available.
    serialized["configured_executor_source"] = executor_source
    return serialized


def _refresh_routing(state: dict[str, Any], payload: dict[str, Any], prompt: str) -> dict[str, Any]:
    routing = _routing_decision(
        state,
        payload,
        prompt,
        explicit_request=bool(state.get("explicit_request")),
    )
    state["routing"] = routing
    route = routing.get("subagent_route")
    review_eligible = route in {"sol-advisor", "sol-active-analysis"}
    spawn_eligible = route in {"terra-implementation", "sol-advisor", "sol-active-analysis"}
    state["final_review_eligible"] = bool(review_eligible)
    state["consultation_eligible"] = bool(spawn_eligible and routing.get("spawn_required"))
    state["intent"] = routing.get("intent", "routine")
    state["sensitivity"] = routing.get("sensitivity", "GREEN")
    return routing


def prompt_text(payload: dict[str, Any]) -> str:
    value = payload.get("prompt") or payload.get("user_prompt") or ""
    return value if isinstance(value, str) else ""


def _hash_material(*values: object) -> str:
    material = "\x1f".join(str(value) for value in values)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def task_identity(payload: dict[str, Any], prompt: str) -> str:
    """Return a non-sensitive identity for the active session task."""
    session = safe_session_id(payload.get("session_id") or payload.get("sessionId"))
    normalized = " ".join(prompt.split()).lower()
    return _hash_material("task", session, normalized)


def normalize_phase(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "initial": "plan",
        "planning": "plan",
        "start": "plan",
        "failure": "stuck",
        "debug": "stuck",
        "blocked": "stuck",
        "completion": "final",
        "stop": "final",
        "review": "final",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in CONSULTATION_PHASES else ""


def phase_from_payload(payload: dict[str, Any], state: dict[str, Any] | None = None) -> str:
    for key in ("phase", "task_phase", "taskPhase", "consultation_phase", "consultationPhase"):
        phase = normalize_phase(payload.get(key))
        if phase:
            return phase
    if state:
        phase = normalize_phase(state.get("phase"))
        if phase:
            return phase
        if state.get("stuck_eligible"):
            return "stuck"
    return "plan"


def decision_fingerprint(state: dict[str, Any]) -> str:
    material = {
        "task_id": state.get("task_id", ""),
        "complexity": state.get("complexity", 1),
        "intent": state.get("intent", "routine"),
        "sensitivity": state.get("sensitivity", "GREEN"),
        "high_impact": bool(state.get("high_impact")),
        "explicit_request": bool(state.get("explicit_request")),
        "impact_reasons": sorted(str(value).lower() for value in state.get("impact_reasons", []) if value),
        "failure_fingerprints": list(state.get("failure_fingerprints", [])),
        "routing_fingerprint": (state.get("routing") or {}).get("decision_fingerprint", "")
        if isinstance(state.get("routing"), dict)
        else "",
    }
    return _hash_material("decision", json.dumps(material, sort_keys=True, separators=(",", ":")))


def advisor_reference(payload: dict[str, Any]) -> str:
    identity_keys = ("agent_id", "agentId", "subagent_id", "subagentId", "thread_id", "threadId")
    for source in advisor_sources(payload):
        for key in identity_keys:
            value = source.get(key)
            if value:
                return _hash_material("verdict", value)
    return ""


def ensure_state_shape(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Upgrade legacy advisory state without retaining unbounded history."""
    try:
        version = int(state.get("version", 1) or 1)
    except (TypeError, ValueError):
        version = 1
    state["version"] = max(version, STATE_VERSION)
    state.setdefault(
        "task_id",
        _hash_material(
            "legacy-task",
            safe_session_id(payload.get("session_id") or payload.get("sessionId")),
        ),
    )
    phase = normalize_phase(state.get("phase"))
    state["phase"] = phase or ("stuck" if state.get("stuck_eligible") else "plan")
    try:
        state["complexity"] = max(1, min(10, int(state.get("complexity", 1) or 1)))
    except (TypeError, ValueError):
        state["complexity"] = 1
    reasons = state.get("impact_reasons", [])
    state["impact_reasons"] = (
        [str(reason).lower() for reason in reasons if str(reason).strip()][:4]
        if isinstance(reasons, list)
        else []
    )
    for key in (
        "high_impact",
        "explicit_request",
        "final_review_eligible",
        "consultation_eligible",
        "stuck_eligible",
        "stop_guard_issued",
        "advisor_started",
        "advisor_completed",
    ):
        state.setdefault(key, False)
    state.setdefault("failure_fingerprints", [])
    if not isinstance(state["failure_fingerprints"], list):
        state["failure_fingerprints"] = []
    state["failure_fingerprints"] = state["failure_fingerprints"][-MAX_FAILURE_FINGERPRINTS:]
    state["failure_count"] = len(state["failure_fingerprints"])
    state.setdefault("consultation_budget", MAX_CONSULTATIONS)
    try:
        state["consultation_budget"] = max(0, min(MAX_CONSULTATIONS, int(state["consultation_budget"])))
    except (TypeError, ValueError):
        state["consultation_budget"] = MAX_CONSULTATIONS
    try:
        state["consultation_count"] = max(
            0,
            min(state["consultation_budget"], int(state.get("consultation_count", 0) or 0)),
        )
    except (TypeError, ValueError):
        state["consultation_count"] = 0
    consulted_fingerprints = state.get("consulted_fingerprints", [])
    state["consulted_fingerprints"] = consulted_fingerprints if isinstance(consulted_fingerprints, list) else []
    state["consulted_fingerprints"] = [
        str(fingerprint)
        for fingerprint in state["consulted_fingerprints"]
        if str(fingerprint).strip()
    ][-MAX_FAILURE_FINGERPRINTS:]
    consulted_phases = state.get("consulted_phases", {})
    state["consulted_phases"] = consulted_phases if isinstance(consulted_phases, dict) else {}
    normalized_phases: dict[str, str] = {}
    for phase, fingerprint in state["consulted_phases"].items():
        normalized_phase = normalize_phase(phase)
        if normalized_phase and fingerprint:
            normalized_phases[normalized_phase] = str(fingerprint)
    state["consulted_phases"] = normalized_phases
    state.setdefault("phase_reservations", {})
    _normalize_phase_reservations(state)
    state.setdefault("prior_verdict_ref", "")
    state.setdefault("prior_verdict_fingerprint", "")
    state["prior_verdict_phase"] = normalize_phase(state.get("prior_verdict_phase"))
    state.setdefault("advisor_reused", False)
    state.setdefault("advisor_budget_exhausted", False)
    state.setdefault("last_consultation_phase", "")
    state["last_consultation_phase"] = normalize_phase(state.get("last_consultation_phase"))
    state.setdefault("routing", {})
    if not isinstance(state["routing"], dict):
        state["routing"] = {}
    for state_key, _payload_keys, default in ROUTING_EVIDENCE:
        if state_key not in state:
            state[state_key] = default
        else:
            parsed = _parse_bool(state.get(state_key))
            state[state_key] = parsed if parsed is not None else False
    state["budget_class"] = _bounded_text(state.get("budget_class"), limit=32) or None
    for override_key in ("task_subagent_override", "session_subagent_override"):
        state[override_key] = _override_record(state.get(override_key))
    state.setdefault("intent", "routine")
    state.setdefault("sensitivity", "GREEN")
    state["budget_remaining"] = max(0, state["consultation_budget"] - state["consultation_count"])
    state["decision_fingerprint"] = decision_fingerprint(state)
    return state


def is_task_boundary(payload: dict[str, Any], prompt: str) -> bool:
    """Recognize an explicit request to start a fresh task state."""
    for key in ("new_task", "newTask", "task_boundary", "taskBoundary", "start_new_task", "startNewTask"):
        if payload.get(key) is True:
            return True
    return False


def merge_existing_state(
    existing: dict[str, Any],
    *,
    complexity: int,
    reasons: list[str],
    high_impact: bool,
    explicit_request: bool,
) -> dict[str, Any]:
    """Merge new prompt evidence without weakening an active obligation."""
    state = ensure_state_shape(dict(existing), {})
    try:
        previous_complexity = int(state.get("complexity", 1) or 1)
    except (TypeError, ValueError):
        previous_complexity = 1
    previous_reasons = state.get("impact_reasons", [])
    if not isinstance(previous_reasons, list):
        previous_reasons = []
    merged_reasons = sorted(
        {str(reason).lower() for reason in previous_reasons if str(reason).strip()}
        | {reason.lower() for reason in reasons}
    )[:4]
    state.update(
        {
            "complexity": max(1, min(10, max(previous_complexity, complexity))),
            "high_impact": bool(state.get("high_impact")) or high_impact,
            "impact_reasons": merged_reasons,
            "explicit_request": bool(state.get("explicit_request")) or explicit_request,
            "final_review_eligible": bool(state.get("final_review_eligible")) or high_impact,
            "consultation_eligible": bool(state.get("consultation_eligible"))
            or explicit_request
            or high_impact,
        }
    )
    state["decision_fingerprint"] = decision_fingerprint(state)
    if state.get("prior_verdict_fingerprint") != state["decision_fingerprint"]:
        state["advisor_completed"] = False
    return state


def should_preserve_state(
    existing: dict[str, Any],
    *,
    payload: dict[str, Any],
    prompt: str,
    high_impact: bool,
    explicit_request: bool,
) -> bool:
    """Keep active state until completion or an explicit task boundary."""
    if is_task_boundary(payload, prompt):
        return False
    if CONTINUATION_RE.search(prompt):
        return True
    # The session is the only stable task boundary available to this hook.
    # Preserve state across ordinary prompts; merge_existing_state() will
    # invalidate a prior verdict only when new decision evidence changes its
    # fingerprint. A new root task must carry an explicit boundary marker.
    return bool(existing)


def _record_red_local_state(payload: dict[str, Any], prompt: str) -> dict[str, Any]:
    """Replace active routing with minimal RED/local-only state without storing the prompt."""
    with locked_state(payload) as state:
        existing = dict(state)
        ensure_state_shape(state, payload)
        session_override = _override_record(existing.get("session_subagent_override"))
        state.clear()
        state.update(
            {
                "version": STATE_VERSION,
                "task_id": _hash_material(
                    "red-task",
                    safe_session_id(payload.get("session_id") or payload.get("sessionId")),
                ),
                "phase": "plan",
                "complexity": 1,
                "high_impact": False,
                "impact_reasons": [],
                "explicit_request": False,
                "final_review_eligible": False,
                "consultation_eligible": False,
                "failure_fingerprints": [],
                "failure_count": 0,
                "decision_fingerprint": "",
                "consultation_budget": MAX_CONSULTATIONS,
                "consultation_count": 0,
                "budget_remaining": MAX_CONSULTATIONS,
                "consulted_fingerprints": [],
                "consulted_phases": {},
                "phase_reservations": {},
                "prior_verdict_ref": "",
                "prior_verdict_fingerprint": "",
                "prior_verdict_phase": "",
                "advisor_reused": False,
                "advisor_budget_exhausted": False,
                "stop_guard_issued": False,
                "advisor_started": False,
                "advisor_completed": False,
                "stuck_eligible": False,
                "routing": {},
                "intent": "routine",
                "sensitivity": "RED",
                "spawn_model_effort_available": False,
                "active_analysis_enabled": False,
                "bounded_scope": False,
                "local_verification_available": False,
                "hard_gates_pass": False,
                "budget_class": None,
                "task_subagent_override": None,
                "session_subagent_override": session_override,
            }
        )
        _refresh_routing(state, payload, prompt)
        state["decision_fingerprint"] = decision_fingerprint(state)
        return dict(state)


def initialize(payload: dict[str, Any]) -> dict[str, Any] | None:
    prompt = prompt_text(payload)
    if not prompt:
        return None
    if is_red(prompt):
        return _record_red_local_state(payload, prompt)
    existing = read_state(payload)
    if existing and CONTINUATION_RE.search(prompt) and not is_task_boundary(payload, prompt):
        with locked_state(payload) as state:
            ensure_state_shape(state, payload)
            state.update(
                merge_existing_state(
                    dict(state),
                    complexity=classification_complexity(payload),
                    reasons=sorted({match.group(1).lower() for match in HIGH_IMPACT_RE.finditer(prompt)})[:4],
                    high_impact=bool(HIGH_IMPACT_RE.search(prompt)),
                    explicit_request=bool(EXPLICIT_RE.search(prompt)),
                )
            )
            _capture_payload_overrides(state, payload)
            _capture_routing_evidence(state, payload)
            _refresh_routing(state, payload, prompt)
            state["decision_fingerprint"] = decision_fingerprint(state)
            return dict(state)
    complexity = classification_complexity(payload)
    reasons = sorted({match.group(1).lower() for match in HIGH_IMPACT_RE.finditer(prompt)})[:4]
    high_impact = bool(reasons)
    explicit_request = bool(EXPLICIT_RE.search(prompt))
    with locked_state(payload) as state:
        existing = dict(state)
        if existing and should_preserve_state(
            existing,
            payload=payload,
            prompt=prompt,
            high_impact=high_impact,
            explicit_request=explicit_request,
        ):
            state.update(
                merge_existing_state(
                    existing,
                    complexity=complexity,
                    reasons=reasons,
                    high_impact=high_impact,
                    explicit_request=explicit_request,
                )
            )
            _capture_payload_overrides(state, payload)
            _capture_routing_evidence(state, payload)
            _refresh_routing(state, payload, prompt)
            state["decision_fingerprint"] = decision_fingerprint(state)
            return dict(state)
        # A session-scoped override survives an explicit task boundary; a
        # task-scoped override deliberately does not.
        session_override = _override_record(
            _payload_value(payload, "session_subagent_override", "sessionSubagentOverride")
        ) or _override_record(existing.get("session_subagent_override"))
        task_override = _override_record(
            _payload_value(payload, "task_subagent_override", "taskSubagentOverride")
        )
        state.clear()
        state.update(
            {
                "version": STATE_VERSION,
                "task_id": task_identity(payload, prompt),
                "phase": "plan",
                "complexity": complexity,
                "high_impact": high_impact,
                "impact_reasons": reasons,
                "explicit_request": explicit_request,
                "final_review_eligible": False,
                "consultation_eligible": False,
                "failure_fingerprints": [],
                "failure_count": 0,
                "decision_fingerprint": "",
                "consultation_budget": MAX_CONSULTATIONS,
                "consultation_count": 0,
                "budget_remaining": MAX_CONSULTATIONS,
                "consulted_fingerprints": [],
                "consulted_phases": {},
                "phase_reservations": {},
                "prior_verdict_ref": "",
                "prior_verdict_fingerprint": "",
                "prior_verdict_phase": "",
                "advisor_reused": False,
                "advisor_budget_exhausted": False,
                "stop_guard_issued": False,
                "advisor_started": False,
                "advisor_completed": False,
                "stuck_eligible": False,
                "routing": {},
                "intent": "routine",
                "sensitivity": "GREEN",
                "spawn_model_effort_available": True,
                "active_analysis_enabled": False,
                "bounded_scope": False,
                "local_verification_available": False,
                "hard_gates_pass": True,
                "budget_class": None,
                "task_subagent_override": task_override,
                "session_subagent_override": session_override,
            }
        )
        _capture_routing_evidence(state, payload)
        _refresh_routing(state, payload, prompt)
        state["decision_fingerprint"] = decision_fingerprint(state)
        return dict(state)


def _is_native_spawn_payload(payload: dict[str, Any]) -> bool:
    for key in ("tool_name", "toolName", "tool"):
        value = payload.get(key)
        if isinstance(value, str):
            final_name = value.strip().lower().replace("-", "_").rsplit(".", 1)[-1]
            if final_name in {"spawn_agent", "spawnagent"}:
                return True
    return "spawn_agent" in command_text(payload).lower()


def _reservation_matches_failure(reservation: dict[str, object], payload: dict[str, Any]) -> bool:
    shape, invocation_id = _spawn_metadata(payload)
    recorded_invocation = _bounded_text(reservation.get("invocation_id"), limit=80)
    recorded_shape = _bounded_text(reservation.get("spawn_shape"), limit=64)
    if recorded_invocation and invocation_id:
        return recorded_invocation == invocation_id
    return bool(recorded_shape and shape and recorded_shape == shape)


def observe_failure(payload: dict[str, Any]) -> dict[str, Any]:
    success = success_from_payload(payload)
    if success is not False:
        return read_state(payload)
    candidate = command_text(payload)
    if not candidate or is_red(candidate):
        return read_state(payload)
    fingerprint = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:16]
    with locked_state(payload) as state:
        ensure_state_shape(state, payload)
        if _is_native_spawn_payload(payload):
            # A failed native spawn never reaches SubagentStart. Release its
            # matching short-lived reservation so a bounded retry can be
            # attempted; unrelated pending phases remain protected.
            reservations = _normalize_phase_reservations(state)
            state["phase_reservations"] = {
                phase: reservation
                for phase, reservation in reservations.items()
                if not _reservation_matches_failure(reservation, payload)
            }
        failures = state.setdefault("failure_fingerprints", [])
        if not isinstance(failures, list):
            failures = []
            state["failure_fingerprints"] = failures
        if fingerprint not in failures:
            failures.append(fingerprint)
            del failures[MAX_FAILURE_FINGERPRINTS:]
        failure_count = len(failures)
        state["failure_count"] = failure_count
        state["decision_fingerprint"] = decision_fingerprint(state)
        if state.get("prior_verdict_fingerprint") != state["decision_fingerprint"]:
            state["advisor_completed"] = False
        if state.get("high_impact") and failure_count >= 2:
            state["stuck_eligible"] = True
            state["phase"] = "stuck"
            _capture_payload_overrides(state, payload)
            _capture_routing_evidence(state, payload)
            _refresh_routing(state, payload, prompt_text(payload))
            state["decision_fingerprint"] = decision_fingerprint(state)
            routing = state.get("routing")
            state["consultation_eligible"] = bool(
                isinstance(routing, dict)
                and routing.get("subagent_route") in {"sol-advisor", "sol-active-analysis"}
                and routing.get("spawn_required")
            )
        return dict(state)


def command_text(payload: dict[str, Any]) -> str:
    values: list[object] = [payload.get("command"), payload.get("cmd")]
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        values.extend([tool_input.get("command"), tool_input.get("cmd")])
    for value in values:
        if isinstance(value, str) and value.strip():
            return value[:2000]
    return ""


def advisor_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [payload]
    for key in ("tool_input", "subagent", "agent", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            sources.append(value)
    return sources


def is_sol_advisor(payload: dict[str, Any]) -> bool:
    sources = advisor_sources(payload)
    values = [
        source.get(key)
        for source in sources
        for key in (
            "agent_name",
            "agentName",
            "agent_type",
            "agentType",
            "subagent_name",
            "subagentName",
            "subagent_type",
            "subagentType",
            "task_name",
            "taskName",
            "agent",
            "name",
        )
    ]
    named_advisor = any(str(value).strip().lower().replace("_", "-") == "sol-advisor" for value in values if value)
    model_values = [source.get(key) for source in sources for key in ("model", "model_name", "modelName")]
    return named_advisor or any(str(value).strip().lower() == SOL_MODEL for value in model_values if value)


def has_no_history_fork(payload: dict[str, Any]) -> bool:
    sources = advisor_sources(payload)
    values = [source.get(key) for source in sources for key in ("fork_turns", "forkTurns", "history_mode", "historyMode")]
    return any(str(value).strip().lower() in {"none", "fresh", "no-history", "no_history"} for value in values if value is not None)


def has_fork_metadata(payload: dict[str, Any]) -> bool:
    return any(
        source.get(key) is not None
        for source in advisor_sources(payload)
        for key in ("fork_turns", "forkTurns", "history_mode", "historyMode")
    )


def has_completion_evidence(payload: dict[str, Any]) -> bool:
    if payload.get("success") is not True:
        return False
    sources = advisor_sources(payload)
    identity_keys = ("agent_id", "agentId", "subagent_id", "subagentId", "thread_id", "threadId")
    return any(source.get(key) for source in sources for key in identity_keys)


def mark_advisor(payload: dict[str, Any], *, completed: bool) -> dict[str, Any]:
    with locked_state(payload) as state:
        ensure_state_shape(state, payload)
        phase = phase_from_payload(payload, state)
        if not completed:
            reservations = _normalize_phase_reservations(state)
            if reservations:
                reserved_phase = reserved_phase_for_start(state, payload)
                if not reserved_phase:
                    # A real SubagentStart must follow the validated native
                    # spawn reservation. Do not let caller-supplied phase
                    # metadata account for an unmatched or ambiguous start.
                    return dict(state)
                phase = reserved_phase
        state["phase"] = phase
        fingerprint = str(state.get("decision_fingerprint", ""))
        if completed:
            state["advisor_completed"] = True
            state["prior_verdict_fingerprint"] = fingerprint
            state["prior_verdict_phase"] = phase
            reference = advisor_reference(payload)
            if reference:
                state["prior_verdict_ref"] = reference
            state["advisor_reused"] = False
        else:
            state["advisor_started"] = True
            consulted_phases = state["consulted_phases"]
            consulted_fingerprints = state["consulted_fingerprints"]
            reservations = _normalize_phase_reservations(state)
            reservations.pop(phase, None)
            state["phase_reservations"] = reservations
            if fingerprint in consulted_fingerprints or phase in consulted_phases:
                state["advisor_reused"] = True
                state["last_consultation_phase"] = phase
                return dict(state)
            count = state["consultation_count"]
            if count >= state["consultation_budget"]:
                state["advisor_budget_exhausted"] = True
                state["budget_remaining"] = 0
                return dict(state)
            consulted_fingerprints.append(fingerprint)
            state["consulted_fingerprints"] = consulted_fingerprints[-MAX_FAILURE_FINGERPRINTS:]
            consulted_phases[phase] = fingerprint
            state["consulted_phases"] = consulted_phases
            state["consultation_count"] = count + 1
            state["budget_remaining"] = max(0, state["consultation_budget"] - state["consultation_count"])
            state["advisor_completed"] = False
            state["advisor_reused"] = False
            state["advisor_budget_exhausted"] = False
            state["last_consultation_phase"] = phase
        return dict(state)


def stop_review_recommendation_pending(state: dict[str, Any]) -> bool:
    """Return whether the report-only Stop hook should record a recommendation.

    This is intentionally not a completion requirement.  The current rollout
    records an eligible final Sol lane for Codex main, while mandatory fresh
    review orchestration remains outside this policy's acceptance target.
    """
    if not state.get("final_review_eligible"):
        return False
    fingerprint = str(state.get("decision_fingerprint", ""))
    try:
        version = int(state.get("version", 1) or 1)
    except (TypeError, ValueError):
        version = 1
    if version >= STATE_VERSION and fingerprint:
        consulted_phases = state.get("consulted_phases", {})
        if isinstance(consulted_phases, dict) and consulted_phases.get("final") == fingerprint:
            return False
        if state.get("prior_verdict_fingerprint") == fingerprint:
            return False
        try:
            budget_remaining = int(state.get("budget_remaining", MAX_CONSULTATIONS) or 0)
        except (TypeError, ValueError):
            budget_remaining = 0
        return budget_remaining > 0
    return not state.get("advisor_completed")


def mark_stop_guard(payload: dict[str, Any]) -> None:
    with locked_state(payload) as state:
        ensure_state_shape(state, payload)
        state["phase"] = "final"
        if state.get("stop_guard_issued"):
            return
        state["stop_guard_issued"] = True
        state["stop_block_count"] = int(state.get("stop_block_count", 0) or 0) + 1


def executor_context(state: dict[str, Any]) -> str:
    routing = state.get("routing")
    if not isinstance(routing, dict) or not state.get("consultation_eligible"):
        return ""
    reasons = ", ".join(str(value) for value in state.get("impact_reasons", [])[:3]) or "explicit request"
    reuse = (
        " An equivalent prior verdict exists; reuse it unless the evidence changed."
        if state.get("prior_verdict_fingerprint") == state.get("decision_fingerprint")
        else ""
    )
    route = str(routing.get("subagent_route", ""))
    arguments = routing.get("spawn_arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    if route == "terra-implementation":
        return (
            "Subagent route: Terra implementation is eligible. Codex main may invoke native `spawn_agent` "
            f"with agent_type=`{arguments.get('agent_type', 'ralph-coder')}`, "
            f"task_name=`{arguments.get('task_name', 'terra_implementation')}`, "
            f"model=`{arguments.get('model', 'gpt-5.6-terra')}`, "
            f"reasoning_effort=`{arguments.get('reasoning_effort', 'high')}`, "
            f"and fork_turns=`{arguments.get('fork_turns', 'none')}`; keep the brief bounded and retain final ownership. "
            f"Basis: effective={routing.get('effective_complexity', state.get('complexity', 1))}/10; "
            f"intent={routing.get('intent', 'implementation')}; executor={routing.get('configured_executor_model', LUNA_MODEL)} "
            f"({routing.get('configured_executor_effort', LUNA_DEFAULT_EFFORT)})."
        )
    return (
        "Sol advisor eligibility: yes. Before a material commitment, invoke native `spawn_agent` with "
        f"agent_type=`{arguments.get('agent_type', 'sol-advisor')}`, "
        f"task_name=`{arguments.get('task_name', 'sol_advisor')}`, model=`{arguments.get('model', SOL_MODEL)}`, "
        f"reasoning_effort=`{arguments.get('reasoning_effort', 'high')}`, and fork_turns=`none`; "
        "put the compact decision brief in the invocation rather than inheriting the conversation. "
        f"Basis: phase={state.get('phase', 'plan')}; effective={routing.get('effective_complexity', state.get('complexity', 1))}/10; "
        f"signals={reasons}; budget_remaining={state.get('budget_remaining', MAX_CONSULTATIONS)}."
        f"{reuse} "
        "Give it a compact decision brief; retain final ownership and verify its advice locally."
    )


def advisor_context(state: dict[str, Any]) -> str:
    reasons = ", ".join(str(value) for value in state.get("impact_reasons", [])[:3]) or "executor request"
    return (
        "Advisor contract: read only. Return no more than 300 words with Verdict, Why, Risks, "
        "smallest next verification, and what would change your mind. Do not take actions or address the user. "
        f"Escalation signals: {reasons}; phase={state.get('phase', 'plan')}; "
        f"budget_remaining={state.get('budget_remaining', MAX_CONSULTATIONS)}."
    )
