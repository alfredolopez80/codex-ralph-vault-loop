# Phase 7 — Cache-first UserPromptSubmit and SessionStart recovery

Status: PASS

## Scope

This phase integrates the deterministic progress engine only into
`UserPromptSubmit` and `SessionStart`. PostToolUse, Stop, automatic legacy
wakeup retirement, hook registration, and real-data migration remain outside
this phase.

The public hook surface now uses one local bridge,
`.codex/hooks/shared/progress_hook.py`, over the canonical
`scripts/plans/progress_context.py` and implementation store. The bridge reads
the global-install source marker when a copied global hook runs, so project and
global dispatch use the same engine without maintaining a second business
implementation or starting a child process.

## UserPromptSubmit contract

The dispatcher follows this order:

1. classify the prompt and block RED before progress, recall, or routing work;
2. resolve active context and model provenance from local payload/files;
3. perform a manifest/state-identity lookup only (no journal or history render);
4. include plan ID, progress generation, and context epoch in the task signature;
5. claim the existing prompt-context cache;
6. return empty on hit/in-flight without progress rendering or durable telemetry;
7. on a miss, compute recall and compatibility components only as needed;
8. compose safety/classification and stable routing metadata before optional
   recovery, recall, and prompt-improvement text.

The legacy rolling checkpoint/continuity narrative is disabled on the normal
path. It is available only with the explicit `RALPH_LEGACY_CONTEXT_COMPAT=1`
compatibility switch required by older migration tests. An explicit progress
request is the only prompt path that asks the progress engine for its bounded
expanded capsule. A second wording in the same epoch may still miss the prompt
cache, but the shared progress ledger prevents a duplicate capsule.

## SessionStart contract

When a valid new store is present, SessionStart is the primary recovery path:

- startup/new-session emits one full capsule for exactly one matching active
  plan;
- resume emits a full capsule or an external-writer delta once for the new
  epoch; same-session writer updates remain silent;
- compact uses a new epoch and emits one full capsule even when generation is
  unchanged;
- clear records a local superseding marker and emits nothing, including later
  same-session startup/retry calls.

Ambiguous or missing active plans are silent. The new-store path resolves
explicit local files only, checks the content-free ledger before reading the
full journal, and does not invoke Git, maintenance/wakeup, dream maintenance,
or an HTML parser. The feature-flagged legacy fallback is bounded to one
implementation-notes HTML source and is never selected for an ambiguous new
store.

The store ledger remains keyed only by project, workspace, session, context
epoch, plan, generation, and capsule kind. Ledger hits are read-only. A line is
written only after a non-empty capsule has been rendered and claimed. Capsules
omit paths, raw hashes, empty sections, and historical narrative, preserve the
authoritative-user/repository-files label, and respect the verified Luna/Terra/
Sol/unknown byte budgets.

## Validation

All commands were local and provider-free. No hook configuration file was
changed and no global installation, push, PR, merge, or real-data migration was
performed.

| Evidence                                                                   |                                                 Result |
| -------------------------------------------------------------------------- | -----------------------------------------------------: |
| Full repository suite (`python3 -m pytest -q`)                             |                     **1106 passed, 5 subtests passed** |
| Prompt/continuity/SessionStart/effective-chain/config-lockstep focused set |                                         **124 passed** |
| Pure context, CLI/store, signature, and bridge set                         |                                          **57 passed** |
| New-store subprocess SessionStart matrix plus global-install smoke parity  |                                          **10 passed** |
| Hook shell suite (`.codex/tests/run-hook-tests.sh`)                        |                                **ALL_HOOK_TESTS_PASS** |
| Ralph memory-flow validation                                               | **PASS** (30 unit, 2 fake integration, 6 write-safety) |
| Changed Python `py_compile`                                                |                                               **PASS** |
| `git diff --check`                                                         |                                               **PASS** |
| Runtime benchmark unit (one measured iteration)                            |                                               **PASS** |

The new subprocess matrix proves startup retry, external-writer resume delta,
compact reinjection, clear supersession, three ledger records only, and zero
reported child processes on every fast-path invocation. The repeated-prompt
unit additionally snapshots every local file byte and mtime: the second hit
performs no full `state.json` or journal read, no progress render, and no
durable write or telemetry append.

## Local benchmark comparison

The committed Phase 0 legacy baseline measured the synthetic `new_session`
recovery at 55.942/64.841 ms p50/p95, 616 output bytes, three HTML parses, and
seven Git children. Its compact path measured 1.781/1.923 ms and 335 bytes but
used the legacy session cache. A ten-sample direct new-store bridge run in this
phase measured:

| New-store path       |      p50 |      p95 | output |
| -------------------- | -------: | -------: | -----: |
| SessionStart startup | 4.744 ms | 5.377 ms |  200 B |
| SessionStart compact | 5.902 ms | 6.173 ms |  200 B |

The direct run excludes fixture construction and reports no child process; the
subprocess matrix independently verifies the same child-free property. The
schema-v2 hook benchmark was rerun with one iteration and no maintenance:
aggregate p50/p95 was 3759.782/3759.782 ms across its full scenario matrix,
with three inferred repeated-prompt cache hits, six measured child processes
from miss-only task-intake/recall work, 163354 persisted bytes, and 1430
estimated context units. Its legacy fixture does not provision a new store,
so those aggregate timings are not presented as a like-for-like new-store
latency claim. The benchmark now infers repeated hits from the bounded
two-prompt fixture because the production hit path intentionally persists
nothing.

## Residual boundaries

- PostToolUse and Stop remain on their prior implementations for Prompt 10.
- Legacy compatibility remains available only behind explicit flags; it is not
  the normal new-store path.
- Provider/account usage remains unavailable and therefore unknown; this phase
  makes no model, advisor, worker, MCP, or network calls.
- Hook registration is unchanged; the consolidated roles already registered by
  the preceding phase remain the only project/global dispatch surface.
