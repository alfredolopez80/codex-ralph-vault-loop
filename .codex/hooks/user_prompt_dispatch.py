#!/usr/bin/env python3
"""Compose UserPromptSubmit context once, with content-free cache state."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
from typing import Any, Mapping

from continuity_prompt_context import is_continuation, maybe_inject, maybe_update_objective
from shared.active_context import ActiveContext, active_context_from_payload
from shared.context_budget import classify_prompt
from shared.context_delta import CacheClaim, claim, discard, finalize
from shared.prompt_context_components import (
    checkpoint_stat_identity,
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
from shared.progress_hook import (
    cheap_lookup,
    emit_lookup,
    progress_event_for_prompt,
    request_for,
)
from shared.sol_advisor import executor_context, initialize, is_task_boundary, read_state
from shared.task_signature import signature_from_prompt
from sol_advisor_prompt_state import routing_context
from user_prompt_capture import capture_safe_prompt
from user_prompt_improve import ADDITIONAL_CONTEXT


def _prompt(payload: Mapping[str, object]) -> str:
    value = payload.get("prompt") or payload.get("user_prompt")
    return value if isinstance(value, str) else ""


def _cheap_route(payload: Mapping[str, object]) -> str:
    for key in ("route", "subagent_route", "route_name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:96]
    for key in ("routing", "routing_decision", "routingDecision"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            for nested_key in ("route", "decision", "route_name", "subagent_route"):
                value = nested.get(nested_key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:96]
    return ""


def _continuity_context(prompt: str, context: ActiveContext) -> str:
    # The canonical progress capsule is owned by SessionStart.  This legacy
    # path remains available only for migration tests and explicit callers;
    # it is never mixed into the normal prompt composition.
    if os.environ.get("RALPH_LEGACY_CONTEXT_COMPAT", "").strip().lower() not in {"1", "true", "yes"}:
        return ""
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
    # A cache hit/in-flight claim is a physical no-op for the prompt path.
    # Runtime observability is deliberately miss-only here so the fast path
    # cannot turn its accounting into a durable write.
    if cache.status in {"hit", "inflight"}:
        return
    try:
        record_event(
            context,
            payload,
            event="user_prompt",
            dispatcher="user_prompt_dispatch",
            duration_ns=time.perf_counter_ns() - started,
            process_count=1,
            child_process_count=2,
            components_considered=["context_guard", "classification", "task_signature", "recall", "routing", "delta"],
            components_executed=["classification", "recall", "routing", "delta"],
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
    finding = classify_prompt(prompt)
    # Safety classification is intentionally first.  No model, store, notes,
    # or routing state is consulted before a RED/block decision is made.
    context = active_context_from_payload(payload, resolve_git=False)
    profile = profile_from_payload(payload)
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

    sensitivity = prompt_sensitivity(prompt, payload)
    generation = memory_generation(context, payload)
    # Only a file-stat marker is consulted before the cache claim.  The
    # checkpoint body and progress journal are miss-only reads.
    checkpoint = checkpoint_stat_identity(context)
    progress = cheap_lookup(context, payload)
    progress_event = progress_event_for_prompt(prompt, payload)
    progress_request = request_for(profile, context, payload, event=progress_event)
    progress_identity = progress.identity
    boundary = is_task_boundary(payload, prompt)
    # Every explicit boundary is a new lifecycle epoch.  A nonce prevents two
    # concurrent or repeated boundaries with identical text from sharing one
    # cache claim before initialize() can reset task-scoped routing state.
    boundary_epoch = f":boundary:{time.time_ns()}" if boundary else ""
    signature_epoch = progress_request.context_epoch + boundary_epoch
    signature = signature_from_prompt(
        prompt,
        context=context,
        profile=profile,
        sensitivity=sensitivity,
        checkpoint_identity=checkpoint,
        progress_plan_id=progress_identity.plan_id if progress_identity else "",
        progress_generation=progress_identity.generation if progress_identity else 0,
        context_epoch=signature_epoch,
    )
    # Routing state is intentionally deferred until after this claim.  Payload
    # routing metadata is cheap and stable enough for the claim fingerprint.
    current_route = _cheap_route(payload)
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
        continuity = _continuity_context(prompt, context)
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
        progress_context = ""
        if progress_event == "explicit":
            try:
                progress_decision = emit_lookup(progress, progress_request, recovery_boundary=True)
                progress_context = progress_decision.capsule if progress_decision.emitted else ""
            except Exception:
                progress_context = ""
        # Safety/classification and stable routing precede optional progress
        # recovery and recall.  The legacy rolling checkpoint is not included
        # unless the explicit compatibility switch above is enabled.
        segments = [classification_context(complexity), route_context, progress_context, continuity, intake]
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
                route=current_route,
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
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        value = stream.read(4 * 1024 * 1024 + 1)
        raw = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        if len(raw.encode("utf-8")) > 4 * 1024 * 1024:
            return 0
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
