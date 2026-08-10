#!/usr/bin/env python3
from __future__ import annotations

from shared.active_context import ActiveContext, active_context_from_payload
from shared.learning import learning_text_from_payload, should_persist_learning
from shared.paths import read_hook_input
from shared.persistence_metrics import WriteResult
from shared.redaction import is_red
from shared.tool_result import success_from_payload
from shared.vault_io import save_learning, save_learning_with_result

LEARNING_FIELDS = ("output", "output_preview", "outputPreview", "result")


def raw_learning_candidate(payload: dict) -> str:
    values = [str(payload.get(field, "")) for field in LEARNING_FIELDS if payload.get(field)]
    response = payload.get("tool_response") or payload.get("toolResponse")
    if isinstance(response, dict):
        values.extend(str(response.get(field, "")) for field in LEARNING_FIELDS if response.get(field))
    return " ".join(values)


def learning_payload(payload: dict) -> dict:
    response = payload.get("tool_response") or payload.get("toolResponse")
    if not isinstance(response, dict):
        return payload
    enriched = dict(payload)
    for field in LEARNING_FIELDS:
        if not enriched.get(field) and response.get(field):
            enriched[field] = response[field]
    return enriched


def run(payload: dict, context: ActiveContext | None = None) -> WriteResult:
    """Persist a candidate only after the dispatcher proved success."""
    if success_from_payload(payload) is not True:
        return WriteResult()
    raw_text = raw_learning_candidate(payload)
    if not raw_text.strip() or is_red(raw_text) or not should_persist_learning(raw_text):
        return WriteResult()
    text = learning_text_from_payload(learning_payload(payload), LEARNING_FIELDS)
    if not text:
        return WriteResult()
    _path, result = save_learning_with_result(
        text,
        source="PostToolUse",
        classification="YELLOW",
        context=context or active_context_from_payload(payload),
    )
    return result


def _legacy_run(payload: dict, context: ActiveContext | None = None) -> bool:
    """Keep the standalone wrapper's historical no-status behavior."""
    raw_text = raw_learning_candidate(payload)
    if not raw_text.strip() or is_red(raw_text) or not should_persist_learning(raw_text):
        return False
    text = learning_text_from_payload(learning_payload(payload), LEARNING_FIELDS)
    if not text:
        return False
    save_learning(text, source="PostToolUse", classification="YELLOW", context=context or active_context_from_payload(payload))
    return True


def main() -> int:
    try:
        _legacy_run(read_hook_input())
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
