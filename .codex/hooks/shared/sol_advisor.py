"""Bounded state for the native GPT-5.6 Sol advisor lane."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Iterator

from .redaction import is_red

STATE_FILE = "sol-advisor.json"
MAX_FAILURE_FINGERPRINTS = 4
MAX_CONSULTATIONS = 2
HIGH_IMPACT_RE = re.compile(
    r"\b(architecture|authorization|auth|schema|database|migration|rollout|deploy|"
    r"public api|external interface|breaking|security|compliance|contract)\b",
    re.IGNORECASE,
)
EXPLICIT_RE = re.compile(r"\b(sol[ -]?advisor|consult(?:ar)?\s+(?:a\s+)?sol)\b", re.IGNORECASE)
CONTINUATION_RE = re.compile(r"^\s*(continue|continua|sigue|resume|where were we)\b", re.IGNORECASE)
SOL_MODEL = "gpt-5.6-sol"


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


def prompt_text(payload: dict[str, Any]) -> str:
    value = payload.get("prompt") or payload.get("user_prompt") or ""
    return value if isinstance(value, str) else ""


def initialize(payload: dict[str, Any]) -> dict[str, Any] | None:
    prompt = prompt_text(payload)
    if not prompt or is_red(prompt):
        return None
    existing = read_state(payload)
    if existing and CONTINUATION_RE.search(prompt):
        return existing
    complexity = classification_complexity(payload)
    reasons = sorted({match.group(1).lower() for match in HIGH_IMPACT_RE.finditer(prompt)})[:4]
    high_impact = bool(reasons)
    explicit_request = bool(EXPLICIT_RE.search(prompt))
    # Complexity is evidence for the executor, never a hard Sol threshold or
    # a multiplier for the consultation budget. A material decision can occur
    # in a short task, so the impact rubric remains independently eligible.
    final_review_eligible = high_impact
    consultation_eligible = explicit_request or final_review_eligible
    with locked_state(payload) as state:
        state.update(
            {
                "version": 1,
                "complexity": complexity,
                "high_impact": high_impact,
                "impact_reasons": reasons,
                "explicit_request": explicit_request,
                "final_review_eligible": final_review_eligible,
                "consultation_eligible": consultation_eligible,
                "failure_fingerprints": [],
                "consultation_count": 0,
                "stop_guard_issued": False,
                "advisor_started": False,
                "advisor_completed": False,
            }
        )
        return dict(state)


def observe_failure(payload: dict[str, Any]) -> dict[str, Any]:
    success = payload.get("success")
    if success is not False:
        return read_state(payload)
    candidate = command_text(payload)
    if not candidate or is_red(candidate):
        return read_state(payload)
    fingerprint = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:16]
    with locked_state(payload) as state:
        failures = state.setdefault("failure_fingerprints", [])
        if not isinstance(failures, list):
            failures = []
            state["failure_fingerprints"] = failures
        if fingerprint not in failures:
            failures.append(fingerprint)
            del failures[MAX_FAILURE_FINGERPRINTS:]
        failure_count = len(failures)
        state["failure_count"] = failure_count
        if state.get("high_impact") and failure_count >= 2:
            state["consultation_eligible"] = True
            state["stuck_eligible"] = True
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
        count = int(state.get("consultation_count", 0) or 0)
        if completed:
            state["advisor_completed"] = True
        else:
            state["advisor_started"] = True
            if count < MAX_CONSULTATIONS:
                state["consultation_count"] = count + 1
        return dict(state)


def needs_stop_review(state: dict[str, Any]) -> bool:
    return bool(
        state.get("final_review_eligible")
        and not state.get("advisor_completed")
    )


def mark_stop_guard(payload: dict[str, Any]) -> None:
    with locked_state(payload) as state:
        state["stop_guard_issued"] = True
        state["stop_block_count"] = int(state.get("stop_block_count", 0) or 0) + 1


def executor_context(state: dict[str, Any]) -> str:
    if not state.get("consultation_eligible"):
        return ""
    reasons = ", ".join(str(value) for value in state.get("impact_reasons", [])[:3]) or "explicit request"
    return (
        "Sol advisor eligibility: yes. Before a material commitment, invoke native `spawn_agent` with "
        "task_name=`sol_advisor`, model=`gpt-5.6-sol`, and fork_turns=`none`; omit agent_type. "
        "Put the compact decision brief in the invocation rather than inheriting the conversation. "
        f"Basis: complexity={state.get('complexity', 1)}/10; signals={reasons}. "
        "Give it a compact decision brief; retain final ownership and verify its advice locally."
    )


def advisor_context(state: dict[str, Any]) -> str:
    reasons = ", ".join(str(value) for value in state.get("impact_reasons", [])[:3]) or "executor request"
    return (
        "Advisor contract: read only. Return no more than 300 words with Verdict, Why, Risks, "
        "smallest next verification, and what would change your mind. Do not take actions or address the user. "
        f"Escalation signals: {reasons}."
    )
