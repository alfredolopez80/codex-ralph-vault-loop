#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from typing import Any, Mapping

from shared.continuation_budget import Reservation, reserve
from shared.objective_gates import GateFinding, collect_hard_findings, phrase_report_codes, route_report_codes
from shared.stop_persistence import mark_promotion_pending, persist_event, persist_handoff
from shared.stop_scope import StopScope, evidence_fingerprint, scope_from_payload
from shared.paths import ralph_home
from shared.post_tool_state import directory_bytes
from shared.runtime_observability import record_event

OUTPUT_LIMIT = 420


def parse_payload() -> dict[str, Any] | None:
    try:
        raw = sys.stdin.read()
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


def _record_reports(scope: StopScope, codes: list[str], runtime_ms: float) -> None:
    if codes:
        persist_event(scope, event="report_only", reason_codes=codes, runtime_ms=runtime_ms)


def _record_stop(
    scope: StopScope,
    payload: Mapping[str, object],
    *,
    findings: list[GateFinding],
    reservation: Reservation | None,
    runtime_ms: float,
    output_bytes: int,
    persistence_bytes: int = 0,
    started_ns: int | None = None,
) -> None:
    codes = [finding.code for finding in findings]
    count = reservation.count if reservation is not None else 0
    persist_event(
        scope,
        event="continuation" if reservation and reservation.allowed else "allow",
        reason_codes=codes,
        runtime_ms=runtime_ms,
        continuation_count=count,
        output_bytes=output_bytes,
    )
    record_event(
        scope.context,
        payload,
        event="stop",
        dispatcher="stop_dispatch",
        duration_ns=max(0, time.perf_counter_ns() - started_ns) if started_ns is not None else max(0, int(runtime_ms * 1_000_000)),
        process_count=1,
        child_process_count=0,
        components_considered=["hard_gates", "quality_evidence", "handoff", "continuation_budget"],
        components_executed=["hard_gates", "handoff", "continuation_budget"],
        components_skipped=["phrase_scan", "route_warning", "heavy_promotion"],
        skipped_reason=["report_only", "deferred"],
        persistence_bytes=persistence_bytes,
        block_reason_code=codes,
        continuation_count=count,
        success=not findings,
        scenario=payload.get("scenario") or ("stop_objective_failure" if findings else "stop_allow"),
        maintenance_deferred=True,
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

    try:
        scope = scope_from_payload(payload)
    except (OSError, TypeError, ValueError):
        sys.stderr.write("stop_dispatch context resolution failed; allowing Stop.\n")
        return 0

    before_persistence = directory_bytes(ralph_home())
    findings, gate_reports = collect_hard_findings(payload, scope)
    report_codes = list(gate_reports.reports)
    report_codes.extend(route_report_codes(payload))
    report_codes.extend(phrase_report_codes(payload))
    if gate_reports.corrupt_states:
        report_codes.append("corrupt_state_recovered")
    runtime_ms = (time.perf_counter_ns() - started) / 1_000_000
    persist_handoff(payload, scope.context, scope)
    mark_promotion_pending(scope, payload)
    _record_reports(scope, report_codes, runtime_ms)

    if not findings:
        _record_stop(
            scope,
            payload,
            findings=[],
            reservation=None,
            runtime_ms=runtime_ms,
            output_bytes=0,
            persistence_bytes=max(0, directory_bytes(ralph_home()) - before_persistence),
            started_ns=started,
        )
        return 0

    fingerprint = _evidence_fingerprint(payload, findings)
    critical = any(finding.critical for finding in findings)
    reservation = reserve(scope, evidence_fingerprint=fingerprint, critical=critical)
    if not reservation.allowed:
        _record_reports(scope, [*report_codes, "continuation_budget_exhausted"], runtime_ms)
        _record_stop(
            scope,
            payload,
            findings=findings,
            reservation=reservation,
            runtime_ms=runtime_ms,
            output_bytes=0,
            persistence_bytes=max(0, directory_bytes(ralph_home()) - before_persistence),
            started_ns=started,
        )
        return 0

    output = _block_response(_short_reason(findings))
    _record_stop(
        scope,
        payload,
        findings=findings,
        reservation=reservation,
        runtime_ms=runtime_ms,
        output_bytes=len(output.encode("utf-8")),
        persistence_bytes=max(0, directory_bytes(ralph_home()) - before_persistence),
        started_ns=started,
    )
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
