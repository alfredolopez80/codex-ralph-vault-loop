"""Pure and bounded components composed by UserPromptSubmit."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .active_context import ActiveContext, project_runtime_root
from .checkpoint_io import CheckpointError, load_latest
from .redaction import is_red, sensitivity_report
from .runtime_budget import child_timeout_for
from .runtime_profile import RuntimeProfile


_TASK_INTAKE: Any | None = None


def complexity_for_prompt(prompt: str) -> int:
    score = 1
    length = len(prompt)
    score += 3 if length > 2_000 else 2 if length > 900 else 1 if length > 250 else 0
    rules = (
        (r"\b(and also|additionally|multiple|several|parallel|adem[aá]s|tambi[eé]n|y luego|despu[eé]s)\b", 1),
        (r"\b(refactor|redesign|migrat|architecture|arquitectura|migraci[oó]n|rediseñ)\w*\b", 2),
        (r"\b(system|framework|pipeline|security|tests?|implement|build|create|agent|vault|hook|loop|sistema|seguridad|pruebas?|construir|crear|agente|b[oó]veda|ciclo)\b", 1),
        (r"\b(audit|validat|verif|quality|gate|integration|e2e|audita|calidad|integraci[oó]n)\w*\b", 1),
        (r"\b(analiza a profundidad|an[aá]lisis detallado|plan antes|antes de modificar|no modifiques|solo planifica|solo plan|movimiento aristot[eé]lico|arist[oó]teles)\b", 1),
        (r"\b(read|list|explain|show|describe|simple|minor|typo|solo lee|solo lista|explica|menor)\b", -1),
        (r"\b(quick|small change|one-line|trivial|r[aá]pido|cambio pequeño|una l[ií]nea)\b", -1),
    )
    for pattern, delta in rules:
        if re.search(pattern, prompt, re.I):
            score += delta
    return max(1, min(score, 10))


def classification_context(complexity: int) -> str:
    if complexity <= 2:
        return f"Prompt classification: complexity={complexity}/10 route=DIRECT."
    if complexity == 3:
        return (
            "Prompt classification: complexity=3/10 route=QUICK_ARISTOTLE. "
            "Quick Aristotle check before acting."
        )
    route = "PLAN_REQUIRED" if complexity <= 6 else "DECOMPOSE_AND_VALIDATE"
    return (
        f"Prompt classification: complexity={complexity}/10 route={route}. "
        "Aristotle First Principles required: verify assumptions, evidence, and completion gates."
    )


def prompt_sensitivity(prompt: str, payload: Mapping[str, object]) -> str:
    explicit = str(payload.get("sensitivity") or payload.get("classification") or "").upper()
    classified = str(sensitivity_report(prompt).get("classification") or "GREEN").upper()
    if explicit in {"GREEN", "YELLOW"}:
        return explicit
    return classified if classified in {"GREEN", "YELLOW"} else "GREEN"


def memory_generation(context: ActiveContext, payload: Mapping[str, object]) -> str:
    explicit = payload.get("memory_generation") or payload.get("memoryGeneration")
    if isinstance(explicit, str) and explicit.strip():
        return hashlib.sha256(explicit.strip()[:256].encode("utf-8")).hexdigest()[:24]
    root = project_runtime_root(context)
    material: list[str] = []
    for relative in ("layers/L4_dream_state.md", "ledgers/learning-events.jsonl", "handoffs/latest.md"):
        path = root / relative
        try:
            stat = path.stat()
            material.append(f"{relative}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            material.append(f"{relative}:missing")
    return hashlib.sha256("|".join(material).encode("utf-8")).hexdigest()[:24]


def checkpoint_identity(context: ActiveContext) -> str:
    try:
        checkpoint = load_latest(context=context)
    except (CheckpointError, OSError, ValueError):
        return ""
    if not isinstance(checkpoint, dict):
        return ""
    return "|".join(
        (
            str(checkpoint.get("content_hash") or "")[:96],
            str(checkpoint.get("updated_at") or "")[:64],
            str(checkpoint.get("status") or "")[:24],
        )
    )


def checkpoint_stat_identity(context: ActiveContext) -> str:
    """Return a content-free checkpoint marker without parsing history."""

    root = project_runtime_root(context)
    for candidate in (root / "checkpoints" / "latest.json", root / "checkpoints" / "latest.jsonl"):
        try:
            stat = candidate.stat()
        except OSError:
            continue
        return f"{candidate.name}:{stat.st_mtime_ns}:{stat.st_size}"
    return ""


def route_from_state(state: Mapping[str, object]) -> str:
    routing = state.get("routing")
    if not isinstance(routing, Mapping):
        return ""
    return str(routing.get("subagent_route") or routing.get("route") or "")[:96]


def _load_task_intake() -> Any | None:
    global _TASK_INTAKE
    if _TASK_INTAKE is not None:
        return _TASK_INTAKE
    path = Path(__file__).resolve().parents[3] / "scripts" / "memory" / "task-intake.py"
    if not path.is_file() or path.is_symlink():
        return None
    spec = importlib.util.spec_from_file_location("ralph_task_intake_dispatch", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _TASK_INTAKE = module
    return module


@contextlib.contextmanager
def _recall_timeout_budget():
    name = "RALPH_RECALL_TIMEOUT_SECONDS"
    previous = os.environ.get(name)
    cap = int(child_timeout_for("UserPromptSubmit", "user_prompt_dispatch"))
    try:
        configured = int(previous) if previous else cap
    except ValueError:
        configured = cap
    os.environ[name] = str(min(cap, max(1, configured)))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def run_intake(prompt: str, context: ActiveContext, profile: RuntimeProfile) -> tuple[str, list[str], str]:
    module = _load_task_intake()
    if module is None:
        return "# Ralph Task Intake\nrecall_status=failed\nmemory_fallback=intake_module_missing", [], "failed"
    try:
        with _recall_timeout_budget():
            result = module.build_task_intake_payload(
                prompt=prompt,
                project=context.project_slug,
                project_id=context.project_id,
                workspace_root=str(context.workspace_root),
                branch=context.branch,
                limit=max(1, profile.recall_items),
                no_recall=False,
            )
        rendered = module.render_markdown(result).strip()
        selected = [str(item)[:96] for item in result.get("selected_memory_ids", []) if isinstance(item, str)][: profile.recall_items]
        clarification = str(result.get("clarification_required") or "no")[:16]
        return rendered, selected, clarification
    except Exception as exc:
        code = "recall_timeout" if "timeout" in type(exc).__name__.lower() else "intake_failed"
        return f"# Ralph Task Intake\nrecall_status=failed\nmemory_fallback={code}", [], "unknown"


def _trim_utf8(value: str, limit: int) -> str:
    data = value.encode("utf-8")
    return value if len(data) <= limit else data[:limit].decode("utf-8", errors="ignore").rstrip()


def compose_context(segments: list[str], profile: RuntimeProfile) -> str:
    hard = profile.prompt_context_bytes_hard
    soft = profile.prompt_context_bytes_soft
    selected: list[str] = []
    for segment in segments:
        clean = segment.strip()
        if not clean or is_red(clean):
            continue
        candidate = "\n\n".join([*selected, clean])
        if len(candidate.encode("utf-8")) <= soft:
            selected.append(clean)
            continue
        remaining = hard - len("\n\n".join(selected).encode("utf-8")) - (2 if selected else 0)
        if remaining > 0:
            selected.append(_trim_utf8(clean, remaining))
        break
    return _trim_utf8("\n\n".join(selected).strip(), hard)


__all__ = [
    "checkpoint_identity", "checkpoint_stat_identity", "classification_context", "complexity_for_prompt", "compose_context",
    "memory_generation", "prompt_sensitivity", "route_from_state", "run_intake",
]
