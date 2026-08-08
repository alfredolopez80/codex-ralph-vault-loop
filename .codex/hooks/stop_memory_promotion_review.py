#!/usr/bin/env python3
"""Compatibility wrapper for the old Stop promotion hook.

The historical entry point remains discoverable for callers and installers,
but it now performs only the safe, idempotent enqueue.  It never launches
dream.py or vault-inbox-review.py on the interactive Stop path.
"""

from __future__ import annotations

from shared.active_context import ActiveContext, active_context_from_payload
from shared.maintenance_queue import enqueue_maintenance
from shared.paths import read_hook_input


def run_assisted_promotion(context: ActiveContext) -> None:
    """Compatibility API: schedule promotion; never run it on Stop."""
    enqueue_maintenance(context, reason_code="assisted_promotion_deferred")


def run_vault_inbox_review(context: ActiveContext) -> None:
    """Compatibility API: schedule inbox review; never run it on Stop."""
    enqueue_maintenance(context, reason_code="vault_review_deferred")


def main() -> int:
    try:
        payload = read_hook_input()
        context = active_context_from_payload(payload)
        enqueue_maintenance(context, reason_code="stop_compatibility_wrapper", payload=payload)
    except Exception:
        # Operational queue failures are fail-open by contract.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
