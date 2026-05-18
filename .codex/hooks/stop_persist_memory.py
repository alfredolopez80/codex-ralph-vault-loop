#!/usr/bin/env python3
from __future__ import annotations

from shared.active_context import ActiveContext, active_context_from_payload
from shared.checkpoint_io import CheckpointError, classify_payload, load_latest, render_checkpoint
from shared.learning import should_persist_learning
from shared.paths import read_hook_input
from shared.redaction import is_red, safe_preview
from shared.vault_io import save_learning, write_handoff


CHECKPOINT_HANDOFF_WORDS = 350


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


def main() -> int:
    payload = read_hook_input()
    context = active_context_from_payload(payload)
    if payload.get("stop_hook_active"):
        return 0
    message = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
    if not isinstance(message, str) or not message.strip():
        return 0
    if is_red(message):
        return 0
    text = safe_preview(message, limit=2_000)
    checkpoint_section, next_step = checkpoint_for_handoff(context)
    summary = f"{checkpoint_section}\n\n## Final Assistant Message\n\n{text}" if checkpoint_section else text
    write_handoff(summary, status="stop-hook", next_step=next_step, context=context)
    if should_persist_learning(text):
        save_learning(text, source="Stop", classification="YELLOW", context=context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
