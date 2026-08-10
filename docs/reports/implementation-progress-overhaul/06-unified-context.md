# Phase 5 — Unified recovery context

Status: PASS

## Scope

This phase adds the pure deterministic progress-context subsystem without
registering it with lifecycle hooks or migrating real data. The public CLI
`scripts/plans/progress.py context` now adapts to the engine; ordinary progress
operations remain store-only.

## Implemented contract

- Current-schema state is the primary source for an explicitly selected plan.
  Automatic selection accepts exactly one matching active manifest plan and
  refuses ambiguity.
- One bounded legacy implementation-notes HTML source is parsed only as a
  recovery fallback. The fallback is never used when a valid new state exists.
- `progress_context.py` renders stable, content-free capsules with no absolute
  paths, raw hashes, complete views, or historical narrative. Verified Luna
  full/delta/expanded limits are 512/256/1024 UTF-8 bytes and 80/35/180 words;
  Terra is 192 bytes; Sol and unknown/unverified are pointer-only at 96 bytes.
- Lifecycle decisions cover ordinary continuation, same-session writer
  suppression, startup/new session, resume, compact, external generation
  change, clear/reset, explicit progress, and unknown-session suppression.
- The store owns `context-emissions.jsonl` and its lock. Records contain only
  the required project/workspace/session/epoch/plan/generation/kind key and a
  deterministic emission ID. Ledger hits perform no writes; a claim occurs
  only after a non-empty capsule is rendered.
- Context epochs are deterministic for startup, resume, compact, reset, and
  explicit boundaries. Hook registration remains intentionally deferred.

## Validation

Focused local evidence:

```text
tests/unit/test_progress_context.py                         10 passed
tests/integration/test_progress_context_cli.py                2 passed
tests/unit/test_implementation_store.py + context ledger   passed
tests/unit/test_progress_cli.py                              10 passed
combined focused context/store/CLI suite                      43 passed
```

The subprocess coverage proves ordinary zero output, startup/new-session full
recovery, same-epoch deduplication without ledger mtime changes, same-session
writer suppression, external delta, compact reinjection, explicit expansion,
unknown-session suppression, and legacy fallback. Pure tests cover source
priority/ambiguity, one-parse fallback, all profile tiers, epoch derivation,
and ledger-key behavior.

The existing hook suites are intentionally not switched in this phase. Real
legacy data is not migrated, and complete JSON/JSONL/HTML/index/view artifacts
remain explicit maintenance outputs only.
