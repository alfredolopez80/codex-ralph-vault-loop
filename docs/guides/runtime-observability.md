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

## Instrumentation boundary

Consolidated dispatchers emit one event per hook process while preserving the
existing stdout contracts. The maintenance runner emits a separate event
after queue/runner work. These values describe local runtime and visible bytes
only; they support scaffold comparisons and do not claim monetary savings.
