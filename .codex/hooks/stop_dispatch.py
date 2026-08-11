#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Mapping

from shared.continuation_budget import Reservation, reserve
from shared.convergent_stop_adapter import evaluate_convergent_stop
from shared.execution_policy import ExecutionPolicyError, configured_activation_mode
from shared.objective_gates import (
    GateFinding,
    collect_hard_findings,
    phrase_report_codes,
    route_report_codes,
)
from shared.persistence_metrics import WriteAccumulator, WriteResult
from shared.progress_runtime import CompletionTransition, complete_progress
from shared.stop_persistence import (
    mark_promotion_pending,
    persist_event,
    persist_handoff,
    terminal_business_claim,
    terminal_business_fingerprint,
)
from shared.stop_scope import StopScope, evidence_fingerprint, scope_from_payload
from shared.post_tool_state import directory_bytes
from shared.runtime_observability import record_event

OUTPUT_LIMIT = 420
MAX_INPUT_BYTES = 4 * 1024 * 1024


def parse_payload() -> dict[str, Any] | None:
    try:
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        value = stream.read(MAX_INPUT_BYTES + 1)
        raw = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
            sys.stderr.write("stop_dispatch input exceeded its bounded limit; allowing Stop.\n")
            return None
        if not raw.strip():
            return {}
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        sys.stderr.write("stop_dispatch invalid JSON payload; allowing Stop.\n")
        return None
    if not isinstance(value, dict):
        sys.stderr.write("stop_dispatch payload is not an object; allowing Stop.\n")
        return None
    return value


def _short_reason(findings: list[GateFinding]) -> str:
    ordered = sorted(findings, key=lambda item: (item.priority, item.code))
    reasons: list[str] = []
    for finding in ordered:
        if finding.reason not in reasons:
            reasons.append(finding.reason)
    reason = "; ".join(reasons[:3])
    if len(reason) > OUTPUT_LIMIT:
        reason = reason[: OUTPUT_LIMIT - 3].rstrip() + "..."
    return reason


def _evidence_fingerprint(payload: Mapping[str, object], findings: list[GateFinding]) -> str:
    parts = [finding.fingerprint or finding.code for finding in findings]
    explicit = payload.get("evidence_fingerprint")
    if isinstance(explicit, str) and explicit.strip():
        parts.append(explicit.strip()[:160])
    return evidence_fingerprint(parts)


def _block_response(reason: str) -> str:
    return json.dumps({"decision": "block", "reason": reason}, ensure_ascii=True)


def _record_reports(scope: StopScope, codes: list[str], runtime_ms: float) -> WriteResult:
    if codes:
        return persist_event(scope, event="report_only", reason_codes=codes, runtime_ms=runtime_ms)
    return WriteResult()


def _reservation_result(reservation: Reservation | None) -> WriteResult:
    if reservation is None:
        return WriteResult()
    return WriteResult(
        changed=reservation.changed,
        bytes_written=reservation.bytes_written,
        files_written=reservation.files_written,
        replacements=reservation.replacements,
        fsync_publications=reservation.fsync_publications,
    )


def _record_observation(
    scope: StopScope,
    payload: Mapping[str, object],
    *,
    findings: list[GateFinding],
    reservation: Reservation | None,
    runtime_ms: float,
    output_bytes: int,
    persistence: WriteAccumulator,
    duplicate: bool,
    started_ns: int | None = None,
) -> WriteResult:
    codes = [finding.code for finding in findings]
    count = reservation.count if reservation is not None else 0
    metrics = persistence.as_dict()
    executed = ["hard_gates"]
    if not duplicate:
        executed.extend(["handoff", "continuation_budget"])
    else:
        # The continuation state was read/evaluated above, but no business
        # writer ran for an identical terminal retry.
        executed.append("continuation_budget")
    return record_event(
        scope.context,
        payload,
        event="stop",
        dispatcher="stop_dispatch",
        duration_ns=max(0, time.perf_counter_ns() - started_ns) if started_ns is not None else max(0, int(runtime_ms * 1_000_000)),
        process_count=1,
        child_process_count=0,
        components_considered=["hard_gates", "quality_evidence", "handoff", "continuation_budget"],
        components_executed=executed,
        components_skipped=["phrase_scan", "route_warning", "heavy_promotion"],
        skipped_reason=["report_only", "deferred"],
        persistence_bytes=metrics["persistence_bytes"],
        persistence_bytes_known=metrics["persistence_bytes_known"],
        persistence_files_written=metrics["files_written"],
        persistence_replacements=metrics["replacements"],
        persistence_appends=metrics["appends"],
        fsync_publications=metrics["fsync_publications"],
        block_reason_code=codes,
        continuation_count=count,
        success=not findings,
        scenario=payload.get("scenario") or ("stop_objective_failure" if findings else "stop_allow"),
        maintenance_deferred=True,
        duplicate_suppressed=duplicate,
    )


def main() -> int:
    started = time.perf_counter_ns()
    payload = parse_payload()
    if payload is None:
        return 0
    if payload.get("stop_hook_active") is True:
        return 0
    event = payload.get("hook_event_name") or payload.get("hookEventName")
    if event not in (None, "", "Stop"):
        return 0

    # The v4 snapshot is opt-in until the repo-local canary and rollout gates
    # are approved.  Shadow evaluation is deliberately silent.  Enforce mode
    # consumes only the bounded v4 decision and never falls through to the
    # legacy reducer, which could otherwise close an incomplete v4 task.
    try:
        activation_mode = configured_activation_mode()
    except ExecutionPolicyError:
        activation_mode = "invalid"
    convergent = evaluate_convergent_stop(payload) if activation_mode in {"shadow", "enforce"} else None
    if activation_mode == "enforce" and convergent is not None:
        if convergent.action == "block":
            sys.stdout.write(_block_response(convergent.reason))
        return 0

    try:
        scope = scope_from_payload(payload)
    except (OSError, TypeError, ValueError):
        sys.stderr.write("stop_dispatch context resolution failed; allowing Stop.\n")
        return 0

    findings, gate_reports = collect_hard_findings(payload, scope, persist_index=False)
    # A progress completion is itself a terminal business mutation.  Do not
    # publish it when an independent Stop hard gate has already failed; the
    # blocked Stop must leave the canonical plan active for correction and a
    # later retry.
    progress = complete_progress(payload, scope.context) if not findings else None
    if progress is None:
        progress = CompletionTransition(reason="stop_hard_gate_failed")
    if progress.error_code:
        findings.append(
            GateFinding(
                progress.error_code,
                progress.error_reason,
                priority=7,
                critical=True,
                source="progress",
                fingerprint=progress.error_code,
            )
        )
    report_codes = list(gate_reports.reports)
    report_codes.extend(route_report_codes(payload))
    report_codes.extend(phrase_report_codes(payload))
    if gate_reports.corrupt_states:
        report_codes.append("corrupt_state_recovered")
    fingerprint = _evidence_fingerprint(payload, findings)
    critical = any(finding.critical for finding in findings)
    reservation = reserve(scope, evidence_fingerprint=fingerprint, critical=critical) if findings else None
    if reservation is not None and reservation.storage_error:
        sys.stderr.write("stop_dispatch continuation state unavailable; hard evidence reported locally and Stop allowed.\n")
        report_codes.append("continuation_state_unavailable")
    elif reservation is not None and not reservation.allowed:
        report_codes.append("continuation_budget_exhausted")

    runtime_ms = (time.perf_counter_ns() - started) / 1_000_000
    output = _block_response(_short_reason(findings)) if reservation is not None and reservation.allowed else ""
    business_fingerprint = terminal_business_fingerprint(
        payload,
        scope,
        findings,
        gate_reports=gate_reports.reports,
    )
    accounting = WriteAccumulator()
    accounting.add(progress.result)
    accounting.add(_reservation_result(reservation))
    with terminal_business_claim(scope, business_fingerprint) as business:
        if not business.duplicate:
            # The progress dispatcher never publishes legacy HTML, Markdown,
            # or implementation-index views.  Those remain explicit CLI or
            # dedicated implementation-notes-hook boundaries.
            accounting.add(persist_handoff(payload, scope.context, scope))
            accounting.add(mark_promotion_pending(scope, payload))
            accounting.add(_record_reports(scope, report_codes, runtime_ms))
            accounting.add(
                persist_event(
                    scope,
                    event="continuation" if reservation is not None and reservation.allowed else "allow",
                    reason_codes=[finding.code for finding in findings],
                    runtime_ms=runtime_ms,
                    continuation_count=reservation.count if reservation is not None else 0,
                    output_bytes=len(output.encode("utf-8")),
                    persisted_bytes=accounting.bytes_written,
                )
            )
            business.commit()

    accounting.add(business.write_result)
    stable_mode = os.environ.get("RALPH_RUNTIME_OBSERVABILITY_MODE", "stable").strip().lower() != "benchmark"
    observe = (not stable_mode) or (not business.duplicate) or bool(findings) or bool(
        reservation is not None and reservation.storage_error
    )
    if observe:
        _record_observation(
            scope,
            payload,
            findings=findings,
            reservation=reservation,
            runtime_ms=runtime_ms,
            output_bytes=len(output.encode("utf-8")),
            persistence=accounting,
            duplicate=business.duplicate,
            started_ns=started,
        )
    if output:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
