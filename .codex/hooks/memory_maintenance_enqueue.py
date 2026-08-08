#!/usr/bin/env python3
"""Interactive-hook entry point for deferred memory maintenance.

This process only writes a bounded descriptor to the local maintenance queue.
It deliberately does not import or launch dream/promotion/vault-review code.
"""

from __future__ import annotations

from shared.active_context import active_context_from_payload
from shared.maintenance_queue import enqueue_maintenance
from shared.paths import read_hook_input


def main() -> int:
    try:
        payload = read_hook_input()
        context = active_context_from_payload(payload)
        enqueue_maintenance(context, reason_code="explicit_enqueue_hook", payload=payload)
    except Exception:
        # Queue persistence is operational and must never block the model.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
