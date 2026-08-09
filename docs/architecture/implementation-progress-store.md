# Canonical implementation-progress store

This document describes the Phase 3 store core. The package is deliberately
not connected to lifecycle hooks yet; legacy HTML/index readers and writers are
unchanged until the later compatibility and migration phases.

## Write boundary and layout

The dedicated resolver identifies the main checkout of the active Git
repository and returns only this exact boundary:

```text
<primary-checkout>/.local-notes/ralph/implementation/
├── manifest.json
├── manifest.lock
├── unplanned-events.jsonl
└── plans/<plan-id>/
    ├── state.json
    ├── events.jsonl
    └── state.lock
```

It does not call or broaden the legacy `implementation_notes_lib` path
validator. A linked worktree is an input context, never a write target.
Absolute paths, traversal, symlink components, non-regular files, and
hardlinked files are rejected. Store directories use mode `0700` and files
use mode `0600` where the platform supports those modes. Locks and JSONL
append targets use `O_NOFOLLOW`; snapshots and the manifest are published with
same-directory temporary files, `fsync`, atomic replacement, and directory
`fsync`.

Plan IDs may contain bounded, slash-separated nested components. Each
component is relative, non-empty, and cannot be `.` or `..`; the complete ID is
bounded to 180 characters and eight components.

Reads are side-effect free. A malformed current-schema file is not silently
discarded: an explicit write/recovery boundary may quarantine it under a
digest-named sibling before rebuilding from trusted evidence. A future schema
raises a hard error and is never quarantined, downgraded, or overwritten.

## State snapshot

`state.json` is a bounded JSON object (target 2 KiB, hard limit 8 KiB). It
contains plan identity/path, generation, lifecycle status and phase, objective,
latest decision, next action, bounded blockers/questions/active paths,
validation statuses, Git/workspace provenance, model provenance, and the last
event linkage. Model provenance is explicit:

```text
model_family  = luna | terra | sol | unknown
model_source  = payload | environment | repository-default | unknown
model_verified = true | false
```

`origin=implementation-progress` and `intent=progress-maintenance` are stored
as stable provenance fields. RED-sensitive values are rejected before any
publication.

The `semantic_hash` is `sha256:<64 hex characters>`. It covers lifecycle and
model-relevant fields while excluding `semantic_hash`, `updated_at`,
`created_at`, writer session/process identifiers, and other observational
metadata. A repeated semantic state is therefore a physical no-op.

## Material events

`events.jsonl` contains only these material kinds:

```text
started, phase_changed, decision, deviation,
blocker_opened, blocker_resolved, question_opened, question_resolved,
validation_changed, completed, reopened, migration_imported,
loose_commit_recorded
```

Each record has an explicit sequence, deterministic event ID, operation ID,
timestamp, bounded summary/reason/next-action fields, references, evidence
codes, Git/model provenance, `previous_event_hash`, and `record_hash`.
Records are bounded to 4 KiB. Sequence and hash-chain failures block mutation
and preserve the source. Reusing an operation ID with the same material
payload succeeds as a no-op; reusing it with a different payload is a hard
logical error. A partial final JSONL line is retained as evidence and is
ignored by the read-only parser until explicit repair.

`unplanned-events.jsonl` shares the bounded record format but accepts only
`loose_commit_recorded`; it is not a plan history and is never folded into the
manifest.

## Manifest

`manifest.json` is a small discovery/status index. It stores repository
identity, a generation, and bounded pointers for registered plans (plan path,
state path, status, branch/workspace identity, semantic hash, and last sequence).
It contains no event history and is rewritten only for plan discovery or a
status/ownership transition. Ordinary phase, decision, validation, or event
updates do not publish it.

Markdown and HTML views are intentionally absent from the canonical layout.
They will be explicit derived exports in a later phase and are never written by
this core.
