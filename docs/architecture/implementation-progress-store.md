# Canonical implementation-progress store

This document describes the canonical store, its public CLI, the recovery-only
context engine, and the remaining hook lifecycle adapter. The engine is
consumed by the consolidated `UserPromptSubmit` and `SessionStart` dispatchers;
`PostToolUse` and `Stop` now integrate only structured validation and explicit
completion transitions. The reversible migration and rollback tools are
project-local maintenance surfaces; real user-data migration and hook
registration changes remain deferred. Legacy HTML/index readers and writers
remain compatibility evidence behind explicit boundaries.

## Public CLI

All ordinary progress operations use one deterministic entrypoint:

```text
python3 scripts/plans/progress.py start --plan <path>
python3 scripts/plans/progress.py record --plan <path> --kind decision --summary <text>
python3 scripts/plans/progress.py phase --plan <path> --phase validation --next <text>
python3 scripts/plans/progress.py validate --plan <path> --gate unit --result pass
python3 scripts/plans/progress.py status --plan <path> --format json
python3 scripts/plans/progress.py context --plan <path> --profile luna --event explicit
python3 scripts/plans/progress.py export --plan <path> --format markdown
python3 scripts/plans/progress.py verify --plan <path>
```

Mutations accept `--operation-id` for retry-safe identity. `--json` and
`--format json` return one bounded machine-readable result; text diagnostics
use stable typed error codes and never echo raw input. `context` is read-only
and profile-bounded (`luna=512`, `terra=192`, `sol/unknown=96` UTF-8 bytes).
Its default `explicit` event renders one expanded request; lifecycle callers
can pass `ordinary`, `startup`, `resume`, `compact`, `clear`, `reset`, or
`external` with an explicit session and epoch.
Exports are derived views: stdout is the default, `--output` is the explicit
persistence boundary, and every render reports source and output digests.
`migrate-legacy --dry-run` inventories every approved plan, nested/worktree
source, index row, derived view, conflict, alias, checksum, schema, reduction,
and warning without creating the new store. `--apply` is the separately
authorized fixture/import boundary and is never called by hooks. It parses
each selected HTML source once, maps the initial template to `started`, merges
compatible index operations by operation identity, imports loose commits into
`unplanned-events.jsonl`, reduces journal events into `state.json`, publishes
the manifest, and verifies hashes, ordering, counts, material fields, and
source provenance. The migration takes a canonical maintenance lock plus the
store's existing per-plan and manifest locks. Divergent copies, aliases, bad
checksums, corrupt/future indexes, missing plans, and orphan views block the
default apply; `--recovery-mode` is an explicit exceptional boundary.

`rebuild-legacy` is a deterministic rollback exporter. Its default is staged
dry-run/stdout reporting with source/output digests. `--apply` replaces only
validated legacy HTML/index/consolidated targets under the canonical manifest
lock, preserves the current legacy pair until validation succeeds, and never
deletes or rewrites the new journal/state.

## Write boundary and layout

The dedicated resolver identifies the main checkout of the active Git
repository and returns only this exact boundary:

```text
<primary-checkout>/.local-notes/ralph/implementation/
├── manifest.json
├── manifest.lock
├── unplanned-events.jsonl
├── context-emissions.jsonl
├── context-emissions.lock
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
model-relevant fields while excluding `semantic_hash`, generation and journal
cursor linkage, `updated_at`, `created_at`, writer session/process identifiers,
and other observational metadata. A repeated semantic state is therefore a
physical no-op; the cursor itself is verified separately against the journal.

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
codes, Git/model provenance, a bounded reduced-state patch,
`operation_payload_hash`, `previous_event_hash`, and `record_hash`. Records
are bounded to 4 KiB. The payload hash is a digest only; raw operation input is
not stored. Sequence and hash-chain failures block mutation and preserve the
source. Reusing an operation ID with the same material payload succeeds as a
no-op even if later operations changed unrelated state; reusing it with a
different payload is a hard logical error. Operation IDs are scoped to one
plan. A partial final JSONL line is retained as evidence and is ignored by the
read-only parser until explicit repair; mutating calls reject it rather than
truncating it.

## Transaction and replay contract

Material plan operations hold the plan's `state.lock` for the complete
append-first transaction:

1. validate the exact store path, current schema, ownership, limits, operation
   ID, RED sensitivity, and Git provenance;
2. compute the event payload hash, reduced-state patch, and candidate snapshot;
3. if the candidate semantic hash is unchanged, return a physical no-op;
4. append exactly one journal record and `fsync` it;
5. atomically replace `state.json` and `fsync` its directory;
6. release the lock.

`state.json` records `last_event_sequence` and `last_event_hash`. A reader
rejects a cursor ahead of the verified journal or a cursor/hash mismatch. A
writer may replay only the verified tail after the cursor, then publishes one
recovery snapshot. If a process stops after append but before replacement, the
next retry therefore applies the event once and does not append a duplicate.
Bad checksums, sequence gaps, hash-chain mismatches, malformed current records,
and future schemas are blocking integrity errors. Repair is an explicit
operation that preserves evidence or quarantines malformed current snapshots;
there is no silent journal truncation or schema downgrade.

The writer result exposes `changed`, `bytes_written`, `files_written`,
`appends`, `replacements`, and `fsync_publications`. An ordinary material
phase update reports at most one journal append and one snapshot replacement;
an unchanged retry reports zero writes and does not change snapshot bytes or
mtime. Status transitions may additionally update the pointer-only manifest.

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

Markdown and HTML views remain intentionally absent from the canonical layout.
Phase 4 exposes them only through explicit `progress.py export` or
`rebuild-legacy` requests; they are never written by ordinary prompt, tool, or
Stop hooks.

## Recovery-only context and context epochs

`scripts/plans/progress_context.py` is a pure renderer and decision engine. It
is not registered with a hook in this phase and it never calls a model,
network, MCP, advisor, or worker. Source selection is strict:

1. one valid current-schema `state.json` for the requested plan, or one
   matching active plan from the manifest for automatic selection;
2. one bounded legacy implementation-notes HTML parse at a recovery boundary;
3. ambiguity or an invalid source produces no automatic selection.

The legacy parser reads and parses at most one HTML source per fallback
operation. It is a recovery bridge, not the normal progress path, and hook
fallback is disabled unless `RALPH_PROGRESS_LEGACY_FALLBACK=1` is explicitly
set. Complete JSON/JSONL/HTML/index/view artifacts are never injected
automatically.

The shared `context-emissions.jsonl` ledger contains only the deduplication key:
`project_id`, `workspace_instance_id`, `session_id`, `context_epoch`, `plan_id`,
`progress_generation`, and `capsule_kind`, plus a deterministic emission ID.
It never stores capsule text, summaries, paths, or raw hashes. A ledger hit is
read-only; the store writes one line only after the engine has produced a
non-empty capsule.

Epochs are caller-visible lifecycle boundaries. `startup`/new session,
`resume`/process boundary, `compact`, `clear`/reset, and explicit reset each
receive a distinct deterministic epoch. Ordinary continuation does not create
an epoch or emit context. A new session with one active plan emits a full Luna
capsule once; an external generation change emits one delta; compaction emits
one full capsule even when the generation is unchanged; an explicit progress
request emits a bounded expanded capsule. Current user instructions and
repository files remain authoritative in every verified Luna capsule. No
absolute paths, historical narrative, or raw hashes are rendered.

## Prompt/session integration (Prompt 9)

`UserPromptSubmit` is cache-first. It classifies safety before resolving model
provenance, performs a content-free manifest/state identity lookup, folds the
plan ID, generation, and context epoch into the task signature, and claims the
existing prompt-context cache before reading journals or rendering recovery.
Hits and in-flight claims return an empty hook response; the normal path does
not update rolling checkpoints or inject a second implementation narrative.
Recall, prompt improvement, and any compatibility checkpoint are miss-only
components and are composed after safety/classification and stable routing
metadata.

`SessionStart` is the primary new-store recovery surface. Startup/new-session
uses one full capsule for one matching active plan, resume uses a full or
external-writer delta only when the epoch/generation key is absent, compact
uses a new full-epoch key, and clear supersedes the local emission state while
remaining silent. A ledger hit is checked before the full journal read. The
fast path resolves only explicit/local checkout paths and reads files directly;
it does not run Git, wakeup, dream maintenance, or an HTML parser for a valid
new-store source. Project/global registration remains the single consolidated
dispatcher contract, so compatibility entrypoints cannot duplicate output.

## PostToolUse, Stop, and checkpoint integration (Prompt 10)

`PostToolUse` first recognizes a structured outcome from a test, build, lint, or
typecheck tool. It then performs the narrow active-state lookup and asks the
canonical store to publish `validation_changed` only when the validation map's
semantic value changes. A repeated successful run is a read-only no-op; a
failure-to-pass transition produces one event and state replacement. Ordinary
reads/writes, partial/streaming results, RED output, ambiguous plans, and
missing new-store state never write progress. Writer-reported byte, file,
append, replacement, and fsync metrics flow into the existing PostToolUse
observability accumulator.

The `Stop` adapter is opt-in per payload completion signal. It cheaply checks
for one matching active state, then reads the bounded state/journal needed to
verify plan identity and approval, canonical repository ownership, progress
provenance, material events, validation gates, branch/commit/workspace, and
schema integrity. A genuine completion publishes one `completed` event and one
state replacement. A terminal retry is a semantic no-op. Corrupt/future state,
identity mismatch, missing material evidence, or incomplete validation becomes
a bounded progress finding under the existing empty-allow / one-JSON-block
Stop contract; completion is never inferred from an invalid source.

When approved planned work updates the normal checkpoint, it carries only
`plan_id`, `generation`, and `semantic_hash`. The checkpoint contains no second
objective, phase, decision, blocker, validation, or next-action narrative, and
the progress adapter never publishes Markdown/HTML/consolidated views or
archive snapshots. Unplanned PostToolUse payloads retain their existing generic
checkpoint behavior.

Normal `scripts/memory/wakeup.py` flow no longer renders implementation notes.
The legacy reader can still be invoked with `--implementation-context` (or
`RALPH_LEGACY_CONTEXT_COMPAT=1`) for bounded migration diagnostics only. The
new migration has been exercised only against deterministic temporary
fixtures; no real local `.ralph/plans` data has been imported in this phase.
