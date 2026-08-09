#!/usr/bin/env python3
"""Compose UserPromptSubmit context once, with content-free cache state."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import time
from typing import Any, Mapping

from continuity_prompt_context import is_continuation, maybe_inject, maybe_update_objective
from shared.active_context import ActiveContext, active_context_from_payload
from shared.context_budget import classify_prompt
from shared.context_delta import CacheClaim, claim, discard, finalize
from shared.prompt_context_components import (
    checkpoint_identity,
    classification_context,
    complexity_for_prompt,
    compose_context,
    memory_generation,
    prompt_sensitivity,
    route_from_state,
    run_intake,
)
from shared.redaction import is_red
from shared.runtime_observability import record_event
from shared.runtime_profile import profile_from_payload
from shared.sol_advisor import executor_context, initialize, is_task_boundary, read_state
from shared.task_signature import signature_from_prompt
from sol_advisor_prompt_state import routing_context
from user_prompt_capture import capture_safe_prompt
from user_prompt_improve import ADDITIONAL_CONTEXT


def _prompt(payload: Mapping[str, object]) -> str:
    value = payload.get("prompt") or payload.get("user_prompt")
    return value if isinstance(value, str) else ""


def _continuity_context(prompt: str, context: ActiveContext) -> str:
    if not is_continuation(prompt):
        maybe_update_objective(prompt, context)
        return ""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        maybe_inject(prompt, context.session_id, context)
    rendered = buffer.getvalue().strip()
    if not rendered:
        return ""
    try:
        value = json.loads(rendered)
    except json.JSONDecodeError:
        return ""
    specific = value.get("hookSpecificOutput") if isinstance(value, dict) else None
    context_value = specific.get("additionalContext") if isinstance(specific, dict) else ""
    return context_value if isinstance(context_value, str) and not is_red(context_value) else ""


def _record(
    context: ActiveContext,
    payload: Mapping[str, object],
    *,
    started: int,
    output: str,
    cache: CacheClaim,
    selected_memory_count: int,
    success: bool,
    skipped: list[str] | None = None,
) -> None:
    try:
        repeated = cache.status in {"hit", "inflight"}
        record_event(
            context,
            payload,
            event="user_prompt",
            dispatcher="user_prompt_dispatch",
            duration_ns=time.perf_counter_ns() - started,
            process_count=1,
            child_process_count=0 if repeated else 2,
            components_considered=["context_guard", "classification", "task_signature", "recall", "routing", "delta"],
            components_executed=[] if repeated else ["classification", "recall", "routing", "delta"],
            components_skipped=skipped or [],
            skipped_reason=[cache.invalidation_reason] if cache.invalidation_reason else [],
            output_bytes=len(output.encode("utf-8")),
            estimated_context_units=(len(output.encode("utf-8")) + 3) // 4,
            cache_hit=cache.status == "hit",
            success=success,
            scenario=payload.get("scenario"),
            selected_memory_count=selected_memory_count,
        )
    except Exception:
        pass


def run(payload: dict[str, Any]) -> str:
    started = time.perf_counter_ns()
    prompt = _prompt(payload)
    if not prompt.strip():
        return ""
    context = active_context_from_payload(payload, resolve_git=False)
    profile = profile_from_payload(payload)
    finding = classify_prompt(prompt)
    if finding is not None:
        if is_red(prompt):
            with contextlib.suppress(Exception):
                initialize(payload)
        output = json.dumps(
            {"decision": "block", "reason": finding.reason},
            ensure_ascii=True,
            separators=(",", ":"),
        )
        _record(
            context,
            payload,
            started=started,
            output=output,
            cache=CacheClaim("bypassed", "unsafe_prompt"),
            selected_memory_count=0,
            success=False,
            skipped=["unsafe_prompt"],
        )
        return output

    continuity = _continuity_context(prompt, context)
    sensitivity = prompt_sensitivity(prompt, payload)
    generation = memory_generation(context, payload)
    checkpoint = checkpoint_identity(context)
    signature = signature_from_prompt(
        prompt,
        context=context,
        profile=profile,
        sensitivity=sensitivity,
        checkpoint_identity=checkpoint,
    )
    if is_task_boundary(payload, prompt):
        # A structured task boundary must reset lifecycle state even when the
        # user repeats the same text.  The cache stores no generation counter,
        # so removing this exact content-free entry is the deterministic miss.
        discard(context, signature)
    existing_state = read_state(payload)
    current_route = route_from_state(existing_state)
    cache = claim(
        context,
        signature,
        memory_generation=generation,
        route=current_route,
        profile=profile.name,
        clarification_state=str(payload.get("clarification_state") or "unknown"),
        checkpoint_hash=checkpoint,
    )
    if cache.status in {"hit", "inflight"}:
        _record(
            context,
            payload,
            started=started,
            output="",
            cache=cache,
            selected_memory_count=len(cache.selected_memory_ids),
            success=True,
            skipped=["unchanged_context"],
        )
        return ""

    try:
        complexity = complexity_for_prompt(prompt)
        enriched = {
            **payload,
            "complexity": complexity,
            "sensitivity": sensitivity,
            "task_signature": signature.value,
        }
        state = initialize(enriched) or {}
        capture_safe_prompt(prompt, context)
        intake, selected_memory_ids, clarification = run_intake(prompt, context, profile)
        route = route_from_state(state)
        route_context = " ".join(
            value for value in (routing_context(state), executor_context(state)) if value
        ).strip()
        # Stable decision metadata must survive a long recall/task card.  It is
        # therefore composed before the variable-length intake segment.
        segments = [continuity, classification_context(complexity), route_context, intake]
        if profile.allow_prompt_improvement:
            segments.append(ADDITIONAL_CONTEXT)
        additional_context = compose_context(segments, profile)
        output = ""
        if additional_context:
            output = json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": additional_context,
                    }
                },
                ensure_ascii=True,
                separators=(",", ":"),
            )
        if cache.status == "miss":
            finalize(
                context,
                signature,
                selected_memory_ids=selected_memory_ids,
                memory_generation=generation,
                route=route,
                profile=profile.name,
                clarification_state=clarification,
                checkpoint_hash=checkpoint,
            )
        _record(
            context,
            payload,
            started=started,
            output=output,
            cache=cache,
            selected_memory_count=len(selected_memory_ids),
            success=True,
        )
        return output
    except Exception:
        if cache.status == "miss":
            discard(context, signature)
        _record(
            context,
            payload,
            started=started,
            output="",
            cache=cache,
            selected_memory_count=0,
            success=False,
            skipped=["operational_failure"],
        )
        return ""


def main() -> int:
    try:
        raw = sys.stdin.read()
        value = json.loads(raw) if raw.strip() else {}
        payload = value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return 0
    output = run(payload)
    if output:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
