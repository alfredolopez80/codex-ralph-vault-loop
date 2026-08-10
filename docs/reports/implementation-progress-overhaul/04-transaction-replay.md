# Phase 4 — replayable, retry-safe progress journal

Status: PASS (new-store core only; runtime consumers and migration remain off)

## Scope and provenance

- Base commit: `04dab29398c65b2303fbd72b2b6573ea810e918e`
- Validation date: 2026-08-10 (local)
- Working branch: `codex/implementation-progress-overhaul`
- Provider/model calls: `0` (no network, MCP, advisor, worker, Terra, Sol, or
  coding-model route was used)
- Raw prompts, responses, note bodies, tool bodies, secrets, and absolute
  sensitive paths: not persisted

This phase hardens the canonical store package without importing it from any
lifecycle dispatcher. Legacy HTML/index/checkpoint behavior is unchanged.

## Commands

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_implementation_store.py tests/unit/test_implementation_store_transactions.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_implementation_store.py tests/unit/test_implementation_store_transactions.py tests/unit/test_implementation_notes_roots.py tests/integration/test_hook_config_lockstep.py tests/integration/test_hooks_basic.py -q
PYTHONPYCACHEPREFIX=/tmp/ralph-pycache python3 -m py_compile .codex/hooks/shared/implementation_store/*.py tests/benchmarks/implementation_store_transaction_benchmark.py
PYTHONPYCACHEPREFIX=/tmp/ralph-pycache python3 tests/benchmarks/implementation_store_transaction_benchmark.py --samples 20
git diff --check
```

## Transaction contract delivered

Every material plan operation takes the per-plan `state.lock` through
validation, candidate reduction, semantic no-op decision, one journal append
plus file `fsync`, and one atomic snapshot replacement plus directory `fsync`.
The lock is released only after the snapshot publication step. The result
metadata is bounded and reports `changed`, bytes, files, append/replacement
counts, and publication `fsync` counts; no payload is recorded in telemetry.

`state.json` now carries and verifies `last_event_sequence` and
`last_event_hash`. Reads reject a cursor ahead of verified history. Writers
reconcile only the unapplied verified tail. A state semantic digest is
recomputed after each reduction and excludes cursor/generation linkage and
observational timestamps while retaining lifecycle, Git, and model fields.

## Operation IDs and recovery

`operation_payload_hash` is a digest-only, per-plan idempotency key. It covers
the requested kind, bounded summaries/reason/next action, references,
evidence codes, state update, and provenance. Thus:

| Case                                    | Result                 | Journal/state writes                                                             |
| --------------------------------------- | ---------------------- | -------------------------------------------------------------------------------- |
| Same plan + same ID + same payload      | success/no-op          | zero when current; one recovery snapshot only after an append-before-state crash |
| Same plan + same ID + different payload | `IdempotencyError`     | zero                                                                             |
| Same ID in different plans              | independent operations | one material append per plan                                                     |

Journal replay is deterministic because each store-created material record
contains a bounded reduced-state patch. Missing/stale snapshots are rebuilt
from the verified first record and its tail. A partial final JSONL line remains
on disk, is ignored by read-only parsing, and blocks mutation until explicit
repair. Bad record checksums, sequence gaps, predecessor-hash mismatches,
malformed current records, and future schemas block without truncation or
silent downgrade. Malformed current snapshots are quarantined only at the
explicit write/recovery boundary.

## Fault and concurrency coverage

The focused transaction tests inject failures:

- before append;
- after append and journal `fsync`;
- while writing the temporary snapshot;
- after snapshot replacement before directory `fsync`;
- concurrent writer plus reader;
- concurrent identical operation IDs;
- concurrent conflicting operation IDs.

They assert preserved journal/state bytes where publication did not complete,
single-event duplicate behavior, exact semantic replay, cursor/hash checks,
temporary-file cleanup, and reader acceptance only for cursors at or behind
verified journal history. Distinct concurrent material operations remain in
sequence order.

Limit coverage includes the target boundary (2 KiB), warning boundary (6 KiB),
hard-minus-one, hard, and hard-plus-one classifications. A candidate above
the 8 KiB state limit is rejected before journal or snapshot bytes change.

## Local benchmark

The benchmark creates a deterministic temporary Git repository and performs 20
material phase updates followed immediately by their unchanged operation-ID
retries. It emits only counters and local latency statistics. One observed run
returned:

| Metric                    | Material update | Unchanged retry |
| ------------------------- | --------------: | --------------: |
| p50 latency               |       13.788 ms |       13.106 ms |
| p95 latency               |       21.248 ms |       20.816 ms |
| max bytes written         |           1,882 |               0 |
| max files written         |               2 |               0 |
| max journal appends       |               1 |               0 |
| max snapshot replacements |               1 |               0 |
| retry mtimes unchanged    |             n/a |          `true` |
| provider calls            |             `0` |             `0` |

The exact run is scheduler/filesystem-sensitive; the helper documents the
noise bound and is the reproducibility source. The material-write target is
met (one append plus one replacement), and unchanged retries are physical
no-ops. The 20-sample p95 is a store-transaction measurement in the local
temporary fixture, not the integrated hook fast-path gate; the approved plan's
`<=5 ms` hot-path target must be re-measured after runtime wiring, with this
phase's value retained as the pre-integration comparison point.

## Focused validation

- New-store and transaction tests: `38 passed`.
- New-store plus legacy root/ownership and hook lockstep/basic suites:
  `135 passed`.
- Hook shell suite: `ALL_HOOK_TESTS_PASS`.
- Python compilation: pass.
- `git diff --check`: pass.

## Exact delta from the approved plan

Delivered now:

1. append-first per-plan transaction ordering with atomic, directory-fsynced
   snapshot publication;
2. digest-only per-plan operation idempotency and conflict blocking;
3. deterministic unapplied-tail replay and missing-snapshot reconstruction;
4. explicit partial-line, checksum, sequence, hash-chain, ownership, and
   future-schema blocking;
5. bounded writer accounting and a repeatable material/retry benchmark;
6. fault-injection and concurrency coverage without runtime consumer changes.

Intentionally deferred:

- CLI compatibility wrappers;
- hook/runtime consumer switching;
- legacy HTML/index migration or dual-write behavior;
- automatic Markdown/HTML/implementation-context views;
- global activation and rollback/export wiring.

No architectural false assumption was found. Provider usage remains
`unknown`/unavailable by design, while the local fixture proves zero actual
provider calls.
