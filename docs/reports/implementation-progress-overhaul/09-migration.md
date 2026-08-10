# Prompt 11 — reversible legacy implementation-notes migration

Status: PASS

## Scope

This phase adds a project-local, explicitly invoked migration boundary from
legacy implementation-notes HTML and schema-v2 index evidence into the
canonical journal/state store. Normal prompt, tool, `PostToolUse`, `Stop`, and
memory paths do not invoke it. No real local `.ralph/plans` data was imported;
all apply checks ran against deterministic temporary Git fixtures.

## Dry-run inventory

`migrate-legacy --dry-run --format json` reports the canonical root and every
discovered Git worktree, approved plan ID (including nested IDs), every plan
Markdown and per-plan HTML copy, index JSON plans/events/loose-commit counts,
index Markdown, consolidated HTML/Markdown, source digests/bytes/mtimes,
expected event and operation counts, estimated state-size reductions, warnings,
and all blocking evidence. It explicitly reports divergent copies, aliases,
bad checksums, corrupt/future schemas, missing plans, and orphan views.

## Apply contract

The importer takes a canonical maintenance lock and delegates writes to the
existing per-plan state locks and manifest lock. Each selected HTML source is
parsed once. The initial template becomes `started`; material entries retain
timestamp, category evidence code, operation ID, normalized status, bounded
reason/impact/references, and Git/session/worktree provenance. Compatible index
events merge by operation identity without duplicate journal records. Loose
commits become idempotent `loose_commit_recorded` rows in
`unplanned-events.jsonl`. The store then reduces events into `state.json` and
publishes the manifest. Verification checks event counts/order/IDs, record
hashes and state cursors, material fields, latest material fields, status,
branch, commit, session, workspace identity, and loose-journal hashes. A
source snapshot proves legacy bytes and mtimes are unchanged.

Unresolved divergent copies, aliases, bad checksums, corrupt/future indexes,
missing plans, and orphan views block default apply. `--recovery-mode` is the
separate explicit exception boundary and is never enabled by hooks.

## Rollback exporter

`rebuild-legacy` deterministically renders compatible per-plan HTML, index JSON,
index Markdown, and consolidated HTML/Markdown views from the new journal and
state. Default execution is staged dry-run/reporting with source and output
digests; `--apply` is explicit. Every output is validated in a temporary stage
before replacement under the manifest lock. The current legacy pair remains
untouched until validation succeeds, and the new journal/state is never
deleted.

## Validation

- `tests/integration/test_legacy_migration.py`: nested fixture import and
  source preservation; worktree-only notes; divergent copies; index event
  merge and loose-commit deduplication; corrupt/future/checksum/alias blockers;
  partial interruption/resume; rerun idempotency; rollback parity and journal
  preservation.
- Focused CLI/store/consolidator/migration suites: 39 passed.
- Python source compilation and `git diff --check`: PASS.

## Deferred follow-up

Real-user-data inventory/apply authorization, hook registration, and any
legacy retirement remain deferred to a separately approved phase. Existing
legacy evidence is neither deleted nor rewritten by this phase.
