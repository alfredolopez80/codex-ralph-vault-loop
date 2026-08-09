# Terminal Stop no-op and writer-accounting phase report

- Phase: `stop-noop-persistence`
- Status: `PASS`
- Captured at: `2026-08-09T21:46:33Z`
- Pre-phase HEAD: `ddf07e2ec6267d090a988fb0050049b44bfc44c1`
- Comparison base: `92255e7d28a3bc84a005951957c953301ba40d7d`
- Executor policy: `gpt-5.6-luna/max`; one local Codex executor, no delegation

This phase reduces only terminal Stop repetition and persistence accounting. It
does not introduce the new progress store, change the selected executor, or
install global configuration.

## Commands and fixture rules

Focused and safety validation:

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_checkpoint_basic.py tests/unit/test_active_context.py tests/unit/test_context_delta.py tests/unit/test_runtime_state_hardening.py tests/unit/test_runtime_profile.py tests/unit/test_subagent_routing.py tests/unit/test_implementation_notes_guard.py tests/unit/test_implementation_index.py tests/unit/test_session_start_dispatch.py tests/unit/test_user_prompt_dispatch.py tests/unit/test_post_tool_dispatch.py tests/unit/test_stop_dispatch.py tests/unit/test_stop_business_noop.py tests/unit/test_runtime_observability.py tests/unit/test_hook_runtime_cost_benchmark.py tests/unit/test_maintenance_queue.py tests/integration/test_stop_handoff_checkpoint.py tests/integration/test_post_tool_checkpoint.py tests/integration/test_continuity_prompt.py tests/integration/test_hook_config_lockstep.py tests/integration/test_hooks_basic.py -q`
- `bash .codex/tests/run-hook-tests.sh`
- `bash scripts/validate-ralph-memory-flow.sh`
- `python3 scripts/setup/smoke-global-hooks.py`
- `bash scripts/setup/doctor-global.sh`
- `python3 scripts/gates/run-gates.py --minimal`
- `RALPH_HOOK_COST_ITERATIONS=5 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 scripts/evals/hook_runtime_cost_benchmark.py --json-out /tmp/implementation-progress-stop-noop-benchmark-final.json --markdown-out /tmp/implementation-progress-stop-noop-benchmark-final.md`
- `PYTHONPYCACHEPREFIX=/tmp/ralph-progress-pyc python3 -m py_compile <changed Python files>`
- `git diff --check`

The focused fixture uses synthetic repositories/workspaces and isolated
temporary `HOME`/`RALPH_HOME` roots. Fixture setup is outside timed regions.
Prompts, assistant responses, note bodies, tool bodies, secrets, customer data,
and temporary absolute paths are not written to the report. The benchmark's
directory scan is an explicit diagnostic measurement; it is not called by the
normal PostTool or Stop dispatchers.

## Stable terminal business contract

`terminal_business_fingerprint()` hashes only bounded business material:
schema, project/workspace/session/task scope, branch and commit, terminal
completion or blocked state, finding codes/criticality/fingerprints, gate
reports, plan identity, validation fields, generation fields, the semantic
checkpoint fingerprint, and the learning-candidate identity. Telemetry
timestamps and raw content are excluded. The persisted marker contains only an
opaque SHA-256 fingerprint keyed by the scoped task.

Hard findings are evaluated before the terminal claim on every invocation.
The claim serializes concurrent Stops under the existing runtime lock. A
duplicate claim skips handoff, implementation-index/view publication, lifecycle
events, maintenance enqueue, and checkpoint/business writers; it never skips a
safety evaluation or changes the supported Stop stdout contract.

Observability is separate from business persistence:

- Stable mode is the default (`RALPH_RUNTIME_OBSERVABILITY_MODE` unset or not
  `benchmark`). A new business operation records one bounded Stop observation;
  an identical successful retry records none; an identical blocked/error retry
  records the safety-relevant observation so hard evidence remains visible.
- Benchmark mode (`RALPH_RUNTIME_OBSERVABILITY_MODE=benchmark`) records every
  Stop observation, including duplicate successes, while the business marker,
  handoff, queue, index, and checkpoint state remain deduplicated.
- The runtime event schema stores hashes, enumerated codes, bounded counters,
  and byte metrics only. Provider/subscription usage remains unavailable and
  is reported as `unknown`.

## Direct no-op evidence

The following measurements compare business files only; the observability
stream is intentionally separate.

| Operation                                                       | First stdout | Identical retry stdout | Retry changed business files | Retry mtime changes | Stop business event lines |
| --------------------------------------------------------------- | -----------: | ---------------------: | ---------------------------: | ------------------: | ------------------------: |
| Successful terminal Stop                                        |          0 B |                    0 B |                            0 |                   0 |                   1 total |
| Failed terminal Stop (same evidence and exhausted continuation) |   93 B block |                    0 B |                            0 |                   0 |                   1 total |

The focused tests additionally compare SHA-256 digests and file sizes, assert
zero replacements/appends/fsync publications on the retry, and exercise six
concurrent identical Stops. Concurrency produces one Stop business event and
one maintenance queue job. Benchmark mode produces two observability records
for the same two invocations but no business-file delta.

Material changes remain distinct:

- a changed critical evidence fingerprint gets a second allowed continuation
  and a second Stop business event;
- changed commit/generation gets a new terminal marker fingerprint and a second
  maintenance job;
- changed validation status gets a second Stop business event;
- the first hard safety finding still emits the supported block JSON. The
  identical retry still evaluates the finding and follows the existing bounded
  continuation rule; it does not rewrite business state.

## Writer-reported persistence accounting

The normal hot paths now aggregate `WriteResult` values from the existing
writer boundaries (atomic JSON replacements, JSONL appends, checkpoint
publication, continuation state, handoff/learning, maintenance queue, and
runtime event storage). A result contains only `changed`, bounded byte/file
counts, replacements, appends, fsync-relevant publications, and a `known`
flag. `WriteResult.unknown()` serializes as `persistence_bytes: null` and
`persistence_bytes_known: false`; unavailable cost is never converted to zero.

Representative direct writer attribution from the isolated fixture:

| Path                                            | Bytes | Known | Files | Replacements | Appends | Fsync publications |
| ----------------------------------------------- | ----: | :---: | ----: | -----------: | ------: | -----------------: |
| PostToolUse read-only dispatch business writers |   465 | true  |     1 |            0 |       1 |                  0 |
| First successful Stop business writers          |  3940 | true  |     6 |            5 |       1 |                  3 |
| Identical successful Stop retry                 |     0 | true  |     0 |            0 |       0 |                  0 |

The runtime observability append is a separate publication and is not folded
into its own event's business-writer total. Uninstrumented compatibility
writers remain explicitly unknown. `report_runtime_overhead.py` preserves an
unknown aggregate whenever any contributing writer is unknown.

`directory_bytes()` remains available only to the explicit benchmark/diagnostic
fixture. The normal `PostToolUse` and `Stop` dispatchers contain no call to the
recursive scanner; the focused regression test replaces both symbols with a
raiser and passes.

## Latency and benchmark headline

The five-iteration benchmark uses full local hook subprocess paths and keeps
the existing diagnostic tree scan outside the normal dispatch code. Values are
local wall-clock p50/p95 and are scheduler-sensitive (compare within the
documented +/-30% noise bound).

| Scenario (Luna fixture label) |  p50 ms |  p95 ms | Diagnostic tree bytes | Output bytes | Estimated units |
| ----------------------------- | ------: | ------: | --------------------: | -----------: | --------------: |
| PostTool read-only            | 148.139 | 153.055 |                  3526 |            0 |               0 |
| PostTool edit                 | 148.014 | 153.480 |                  8104 |            0 |               0 |
| PostTool edit + test          | 312.627 | 314.012 |                 15844 |            0 |               0 |
| Stop allow                    |  92.498 |  96.280 |                  6050 |            0 |               0 |
| Stop objective failure        |  98.553 | 116.994 |                  8024 |          173 |              44 |

The existing heuristic remains `ceil(output UTF-8 bytes / 4)` and is not a
token, credit, or subscription measurement. The benchmark matrix recorded
`advisor_count=0` and `child_process_count=0` for these hook scenarios; no
external provider, MCP, worker, or advisor call was made. Provider/account
usage is `unknown`, not zero.

## Before/after target deltas

The prior physical-no-op report measured the legacy terminal retry at
4 files / 8,813 bytes / 2 replacements / 1 append / 4 mtime changes / 2
recursive scans. The direct stable retry is 0 / 0 / 0 / 0 / 0 / 0 for those
business metrics. The prior Stop-allow full-tree diagnostic row was 8 files /
8,834 bytes / 2 replacements / 0 appends / 2 mtime changes / 2 scans; the new
writer-attributed first-operation row is 6 files / 3,940 bytes / 5
replacements / 1 append / 3 fsync publications, while the benchmark's full
diagnostic tree row is 6,050 bytes. These scopes are intentionally labeled
separately and are not claimed to be byte-for-byte equivalent totals.

| Approved-plan target                                                     | This phase evidence                                                              |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| Identical terminal Stop is a physical business no-op                     | PASS: zero changed bytes/digests/sizes/mtimes and one lifecycle event total      |
| No duplicate checkpoint, handoff, index/view, or maintenance publication | PASS: duplicate path skips all business writers; concurrency gives one queue job |
| Hard safety findings remain active                                       | PASS: hard gates run before dedupe; first failure blocks with supported JSON     |
| Normal PostTool/Stop recursive scans                                     | PASS: zero calls; scans remain explicit benchmark-only                           |
| Writer-reported bytes with unknown preserved                             | PASS: bounded `WriteResult`; unknown remains `null`/false                        |
| Stable observability does not append redundant successful Stop records   | PASS: stable duplicate success suppressed; benchmark mode records it             |
| Provider/advisor/worker accounting                                       | Provider usage `unknown`; measured external/advisor/worker calls `0`             |

## Limitations and risks

- The benchmark's diagnostic full-tree byte delta includes explicit fixture
  scanning and is not a replacement for writer attribution.
- Legacy compatibility writers that do not expose a result remain `unknown`;
  this is visible in telemetry and reports rather than coerced to zero.
- Direct handoff compatibility publication still uses its existing bounded
  files; the terminal marker prevents repeated publication for the same
  semantic fingerprint.
- Provider/subscription usage cannot be measured locally. Sol/unknown labels in
  the benchmark are synthetic fixture profiles and do not represent model
  calls.
- Latency is process/scheduler-sensitive; integer writer and no-op counters are
  expected to be exact for the fixture.
