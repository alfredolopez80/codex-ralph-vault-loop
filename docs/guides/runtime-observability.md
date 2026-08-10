# Privacy-safe runtime observability

Phase 15 adds a versioned local event stream for attributing hook scaffolding
to work. The stream is scoped by sanitized project id and remains outside the
repository and vault.

## Event schema

Each JSONL record has `schema_name=ralph_runtime_overhead` and
`schema_version=1`. Supported event names are `session_start`, `user_prompt`,
`pre_tool`, `post_tool`, `stop`, `subagent`, and `maintenance`.

Records contain monotonic duration in nanoseconds; hashed session, turn, and
task identifiers; safety profile/model family plus model source and verified
provenance; tool family; bounded component lists;
process counts; output bytes; estimated context units; persistence bytes;
reason codes; continuation/advisor counts; cache/duplicate flags; source
scope; and the fixed `subscription_usage_measured=false` field.

Only enumerated codes are persisted. Prompt text, assistant text, tool bodies,
memory bodies, transcripts, sensitive paths, and private values are rejected by
the writer. Bad input lines are quarantined as line number plus digest, never
copied verbatim.
Tool labels in the cost ledger use the same sensitive-content redactor and a
bounded preview before they are classified or persisted; a caller cannot turn
`tool_name` into a raw-body or credential side channel. RED checkpoint
rejection events retain truthful bounded append/replacement/fsync metrics while
the rejected body remains local to the classifier.

The default file is below the configured `RALPH_HOME` runtime value:

```text
projects/<project-id>/observability/runtime-events.jsonl
```

Files are mode 0600, lock protected, and rotated at bounded size
(`RALPH_RUNTIME_EVENTS_MAX_BYTES`, default 4 MiB) and bounded count
(`RALPH_RUNTIME_EVENTS_MAX_FILES`, default 3). Runtime filesystem failures
fail open for the hook. The writer measures with `time.perf_counter_ns()`;
maintenance events are marked deferred.

## Reporting

```bash
python3 scripts/evals/report_runtime_overhead.py \
  --input RALPH_HOME/projects/<project-id>/observability/runtime-events.jsonl \
  --quarantine-out /tmp/ralph-runtime-quarantine.jsonl \
  --json-out /tmp/ralph-runtime-overhead.json \
  --markdown-out /tmp/ralph-runtime-overhead.md
```

Reports group by profile, model family, event, and scenario. They show p50/p95,
processes, output, estimated context, persistence, continuations, advisors,
and blocked/duplicate observations. Interactive and deferred maintenance are
separate; maintenance is excluded from interactive timing. Empty or partial
samples receive low/medium confidence rather than fabricated zeroes.

`estimated_context_units` is `ceil(output_bytes / 4)`, a local comparison
heuristic rather than model accounting. The stream cannot observe internal
units, cached input, output billing, account limits, credits, or real
subscription consumption.

`model_source=repository-default` is intentionally not equivalent to a
verified active turn. The source and boolean `model_verified` fields are
content-free provenance labels only; they do not change the configured
executor. Progress-maintenance records are local bookkeeping and carry no
advisor or worker allowance.

An optional CSV/JSON export may be passed with `--usage`. It is supplied by the
user, accepts only unambiguous ISO timestamps, and is reported separately as
`user_supplied_usage` with `verified=false`. It is never scraped, authenticated,
or joined to events by ambiguous timestamps.
No provider or account usage is inferred from these local ledgers; absence of
an operator-supplied export is reported as unknown rather than zero.

## Instrumentation boundary

Consolidated dispatchers emit one event per hook process while preserving the
existing stdout contracts. The maintenance runner emits a separate event
after queue/runner work. These values describe local runtime and visible bytes
only; they support scaffold comparisons and do not claim monetary savings.

## Release-candidate reader/writer limits

The observability writer and report reader are bounded independently of the
canonical progress store. A report accepts at most 64 input files, 32 MiB per
file, 100,000 records/usage rows, 4,096 profile groups, and 512 KiB of each
serialized JSON/Markdown report. Quarantine output is capped at 1 MiB with a
4 KiB digest-only line limit. Files are opened without following symlinks,
must be regular and singly linked, and are checked again after streaming. A
rotation or append that cannot prove the complete write returns an unknown
result and never claims an exact byte count.

Hook stdin and captured compatibility-component output are bounded as well.
Oversized input is treated as an unknown/allow-safe dispatch condition; it is
not copied into diagnostics. No report, ledger, cache hit, or normal dispatch
performs a recursive runtime scan or creates a view as a side effect. The
persisted `model_source`, `model_verified`, and model-family fields remain
content-free provenance labels; progress maintenance cannot route through
Terra, Sol, advisors, workers, or MCPs.
