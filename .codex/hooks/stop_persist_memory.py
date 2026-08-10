#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re

from shared.active_context import ActiveContext, active_context_from_payload
from shared.checkpoint_io import CheckpointError, classify_payload, load_latest
from shared.learning import extract_validated_learning, payload_indicates_failure
from shared.paths import read_hook_input
from shared.persistence_metrics import WriteResult
from shared.redaction import is_red
from shared.vault_io import save_learning_with_result, write_handoff_with_result

MEMORY_TRACE_KEYS = ("selected_memory_ids", "memory_rejected", "recall_status", "fallback_used")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


def _safe_id(value: object, limit: int = 96) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return _SAFE_ID_RE.sub("_", text).strip("_.:-")[:limit]


def checkpoint_for_handoff(context: ActiveContext) -> str:
    try:
        checkpoint = load_latest(context=context)
    except CheckpointError:
        return ""
    if not checkpoint or str(checkpoint.get("classification", "")).upper() == "RED":
        return ""
    if classify_payload(checkpoint)["classification"] == "RED":
        return ""
    checkpoint_id = _safe_id(checkpoint.get("content_hash")) or "unknown"
    phase_value = str(checkpoint.get("current_phase") or "")
    phase_id = hashlib.sha256(phase_value.encode("utf-8", errors="replace")).hexdigest()[:16] if phase_value else "unknown"
    validation = _safe_id(checkpoint.get("validation_status"), 32) or "unknown"
    status = _safe_id(checkpoint.get("status"), 32) or "unknown"
    return f"## Rolling Checkpoint\n\n- checkpoint_id={checkpoint_id} phase_id={phase_id} validation={validation} status={status}"


def memory_trace_for_handoff(payload: dict) -> str:
    lines: list[str] = []
    selected = payload.get("selected_memory_ids") or payload.get("selectedMemoryIds")
    if isinstance(selected, list):
        identifiers = [_safe_id(item) for item in selected]
        identifiers = [item for item in identifiers if item][:8]
        if identifiers:
            lines.append("selected_memory_ids=" + ",".join(identifiers))
    rejected = payload.get("memory_rejected")
    if isinstance(rejected, (list, tuple, set, dict)):
        lines.append(f"memory_rejected_count={len(rejected)}")
    recall = _safe_id(payload.get("recall_status"), 32)
    if recall:
        lines.append(f"recall_status={recall}")
    if isinstance(payload.get("fallback_used"), bool):
        lines.append(f"fallback_used={str(payload['fallback_used']).lower()}")
    if not lines:
        return ""
    return "## Memory Trace\n\n" + "\n".join(f"- {line}" for line in lines)


def run(payload: dict, *, context: ActiveContext | None = None) -> WriteResult:
    try:
        context = context or active_context_from_payload(payload, resolve_git=False)
        if payload.get("stop_hook_active"):
            return WriteResult()
        message = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
        if not isinstance(message, str) or not message.strip():
            return WriteResult()
        if is_red(message):
            return WriteResult()
        checkpoint_section = checkpoint_for_handoff(context)
        memory_trace = memory_trace_for_handoff(payload)
        marker = (
            "## Current Goal\n\n"
            f"- task: observed session_id={_safe_id(context.session_id)} "
            f"branch={_safe_id(context.branch)} head={_safe_id(context.sha)}"
        )
        sections = [section for section in (marker, checkpoint_section, memory_trace) if section]
        summary = "\n\n".join(sections)
        _path, result = write_handoff_with_result(
            summary,
            status="stop-hook",
            next_step="Re-read current project state and verify pending work.",
            context=context,
        )
        if not payload_indicates_failure(payload):
            learning = extract_validated_learning(message)
            if learning:
                # Preserve the bounded validated candidate for deferred human-
                # review maintenance, but keep it out of normal recall.
                _candidate, learning_result = save_learning_with_result(
                    learning,
                    source="Stop",
                    classification="YELLOW",
                    context=context,
                    candidate_only=True,
                )
                if learning_result.changed:
                    result = WriteResult(
                        changed=True,
                        bytes_written=(result.bytes_written or 0) + (learning_result.bytes_written or 0)
                        if result.bytes_written is not None and learning_result.bytes_written is not None
                        else None,
                        files_written=tuple(result.files_written) + tuple(learning_result.files_written),
                        replacements=result.replacements + learning_result.replacements,
                        appends=result.appends + learning_result.appends,
                        fsync_publications=result.fsync_publications + learning_result.fsync_publications,
                        known=result.known and learning_result.known,
                    )
        return result
    except Exception:
        return WriteResult.unknown()


def main() -> int:
    run(read_hook_input())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
