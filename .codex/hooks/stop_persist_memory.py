#!/usr/bin/env python3
from __future__ import annotations

from shared.active_context import ActiveContext, active_context_from_payload
from shared.checkpoint_io import CheckpointError, classify_payload, load_latest, render_checkpoint
from shared.learning import extract_validated_learning, payload_indicates_failure
from shared.paths import read_hook_input
from shared.redaction import is_red, safe_preview
from shared.vault_io import save_learning, write_handoff


CHECKPOINT_HANDOFF_WORDS = 350
MEMORY_TRACE_KEYS = ("selected_memory_ids", "memory_rejected", "recall_status", "fallback_used")


def checkpoint_for_handoff(context: ActiveContext) -> tuple[str, str]:
    try:
        checkpoint = load_latest(context=context)
    except CheckpointError:
        return "", ""
    if not checkpoint or str(checkpoint.get("classification", "")).upper() == "RED":
        return "", ""
    if classify_payload(checkpoint)["classification"] == "RED":
        return "", ""
    rendered = render_checkpoint(checkpoint, max_words=CHECKPOINT_HANDOFF_WORDS).strip()
    if not rendered or is_red(rendered):
        return "", ""
    next_action = str(checkpoint.get("next_action") or "").strip()
    next_step = safe_preview(next_action, limit=500) if next_action and not is_red(next_action) else ""
    return f"## Rolling Checkpoint\n\n{rendered}", next_step


def memory_trace_for_handoff(payload: dict) -> str:
    lines: list[str] = []
    for key in MEMORY_TRACE_KEYS:
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        candidate = f"{key}={safe_preview(value, limit=500)}"
        if not is_red(candidate):
            lines.append(candidate)
    if not lines:
        return ""
    return "## Memory Trace\n\n" + "\n".join(lines)


def main() -> int:
    try:
        payload = read_hook_input()
        context = active_context_from_payload(payload)
        if payload.get("stop_hook_active"):
            return 0
        message = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
        if not isinstance(message, str) or not message.strip():
            return 0
        if is_red(message):
            return 0
        text = safe_preview(message, limit=6_000)
        checkpoint_section, next_step = checkpoint_for_handoff(context)
        memory_trace = memory_trace_for_handoff(payload)
        sections = [section for section in (checkpoint_section, memory_trace, f"## Final Assistant Message\n\n{text}") if section]
        summary = "\n\n".join(sections)
        write_handoff(summary, status="stop-hook", next_step=next_step, context=context)
        if not payload_indicates_failure(payload):
            learning = extract_validated_learning(text)
            if learning:
                save_learning(learning, source="Stop", classification="YELLOW", context=context)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
