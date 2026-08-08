# PHASE 10 - Deferred Memory Maintenance

> Historical note: the earlier checkpoint with this number covered the
> deterministic scripts under `scripts/gates` and remains recoverable in git
> history. This file now records the active runtime-maintenance phase requested
> by the optimization sequence.

Date: 2026-08-08
Repository: `codex-ralph-vault-loop`

## Previous checkpoint

`docs/migration/checkpoints/PHASE_09.md` exists and is marked `PASS`.

## First-principles decision

Interactive hooks have two irreducible responsibilities: preserve safety and
handoff evidence, then return a valid hook response quickly. Dream
consolidation, assisted promotion, and inbox review are maintenance work;
their output cannot change the Stop decision already made. The boundary is
therefore rebuilt around a small descriptor-only queue and an explicit runner,
instead of hiding heavyweight subprocesses behind shorter timeouts.

## Scope and implementation

- `maintenance_queue.py` provides schema-versioned project queues,
  idempotency, debounce, TTL/eviction, singleton locking, leases, bounded
  retries/dead-lettering, atomic writes, corrupt-file quarantine, symlink
  rejection, restrictive permissions, and sanitized event logs.
- `memory_maintenance_enqueue.py` and the compatibility Stop wrapper enqueue
  and exit 0; neither launches dream or vault-review code.
- `stop_dispatch.py` retains handoff and objective gates while adding the
  deferred marker. `session_start_wakeup.py` enqueues before immediately
  running `wakeup.py`; it no longer starts the dream scheduler.
- `run-pending-maintenance.py` is the controlled runner. It invokes the
  existing scheduler only after claiming a job, keeps scheduler output away
  from the model path, and reports runner metrics separately.
- Ambiguous inbox candidates remain `ask_user`; promotion decisions are not
  changed.

The host configuration does not provide a verified asynchronous SessionEnd
contract in this repository, so no orphan daemon or unbounded background child
was introduced. A local doctor, cron, or approved automation may invoke the
explicit runner. This limitation is intentional and documented.

## Validation

- Queue unit coverage: idempotency, branch/generation separation, corrupt
  recovery, bounded retry/dead-letter, concurrency, TTL, symlink fail-open,
  and raw-content exclusion.
- Lifecycle and vault integration call the explicit runner after enqueue;
  direct Stop remains stdout-empty and fast.
- SessionStart source contains no scheduler subprocess; the compatibility
  wrapper contains no subprocess invocation.
- Runner JSON reports `child_process_count`, processed jobs, failures, and
  `runner_runtime_ms`; interactive hook latency remains separate.

## Risks and limits

- Queue delivery is at-least-once. Existing sinks must remain idempotent; a
  crash after a sink write and before completion can retry.
- The explicit runner must be scheduled or invoked by an operator; the hook
  path does not claim maintenance has completed.
- Tests use temporary runtime and vault fixtures only. User-level Codex
  configuration and real vault data were not changed.

## Benchmark delta

The ten-iteration report is `/tmp/ralph-hook-phase10.json` with
`subscription_usage_measured=false`. Interactive Stop allow measured p50/p95
`81.497/85.312 ms`; objective-failure Stop measured `82.332/90.516 ms`, with
one continuation per failed fixture and no plain output on allow. Deferred
maintenance is reported separately: Stop enqueue p95 is `82.733 ms` for the
allow fixture and `84.693 ms` for the objective-failure fixture; the runner
p95 is `193.478/190.346 ms` and launches one known scheduler child. Session
start enqueue p95 is `790.030 ms` because wakeup remains in that hook, while
the maintenance runner p95 is `188.517 ms`.

Comparing the candidate with the valid Phase 09 report yields `cambio no
comparable` at a 5% noise threshold because the aggregate contains both small
runtime improvements and noisy prompt-hook deltas; it reports zero semantic
gate changes. Stop p95 remains below the strict `max(250 ms, 40% baseline)`
target. The older 00-baseline file in `/tmp` is not valid standalone JSON, so
no delta against it is claimed.

Decision: PASS
