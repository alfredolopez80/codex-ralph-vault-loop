# Runtime optimization v2 — Phase 16 A/B evaluation

Date: 2026-08-08
Baseline: `4784a55dd2b33e874ff8e615c6afe1488a8402dc` (the SHA recorded by
`docs/reports/runtime-optimization-v2/00-baseline.md`)
Candidate: `f3ea66c33bd0a7ffd91d0400c9db7acd6724f5d1`

## Method and boundaries

The baseline was checked out in a temporary detached worktree at
`/tmp/codex-ralph-baseline`; the candidate worktree was not reset. Each
benchmark invocation used a separate temporary Ralph home, empty memory/vault
directories, and a deterministic fixture payload. One warmup invocation was
run separately, followed by seven measured iterations. Monotonic wall time,
stdout bytes, local persistence deltas, block/continuation counts, and handler
counts are local observations only.

The historical baseline benchmark predates the versioned Phase 15 schema and
does not accept `--json-out`. The compatibility comparator therefore rejected
it as `cambio no comparable` (`schema_version` missing), as required. The
tables below use an explicit, read-only normalization of the two benchmark
outputs; no zeros were substituted for missing data.

Provider/account usage, internal model units, cached input, billing, and
credits were not measured. `estimated_context_units` is the existing local
`ceil(stdout bytes / 4)` heuristic. Child process trees are `unknown` unless
the target emitted a measurable value; unknown is never reported as zero.

## Structural handler comparison

| Event            | Baseline configured | Candidate configured |            Delta | Target status                          |
| ---------------- | ------------------: | -------------------: | ---------------: | -------------------------------------- |
| SessionStart     |                   1 |                    1 |                0 | unchanged                              |
| UserPromptSubmit |                   5 |                    5 |                0 | target of 1 not reached in this branch |
| PreToolUse       |                   3 |                    3 |                0 | target of 1 not reached in this branch |
| PostToolUse      |                   6 |                    1 |      -5 (-83.3%) | pass                                   |
| SubagentStart    |                   1 |                    1 |                0 | unchanged                              |
| SubagentStop     |                   1 |                    1 |                0 | unchanged                              |
| Stop             |                   8 |                    1 |      -7 (-87.5%) | pass                                   |
| **Total**        |              **25** |               **13** | **-12 (-48.0%)** | no handler-count increase              |

The unchanged UserPromptSubmit and PreToolUse counts are an explicit Phase 16
finding, not an optimization performed in this phase.

## Project-only runtime comparison

Values are sums of project-only handler p50/p95 samples for the seven measured
iterations. They are process-boundary latency proxies, not model latency.

| Event                          | Baseline p50 ms | Candidate p50 ms |      Delta | Baseline p95 ms | Candidate p95 ms |  Delta | Verdict                                          |
| ------------------------------ | --------------: | ---------------: | ---------: | --------------: | ---------------: | -----: | ------------------------------------------------ |
| SessionStart startup           |           725.7 |             47.0 |     -93.5% |           802.3 |             47.6 | -94.1% | pass; candidate fast path reports child count 0  |
| UserPromptSubmit               |          2166.0 |           1643.1 |     -24.1% |          2289.5 |           1807.6 | -21.0% | improvement; five handlers remain                |
| PreToolUse                     |           128.4 |            142.1 |     +10.7% |           130.8 |            148.7 | +13.7% | soft regression/noise warning; safety tests pass |
| PostToolUse                    |           243.7 |             71.1 |     -70.8% |           261.3 |             75.8 | -71.0% | pass; one dispatcher                             |
| Stop (allow/failure aggregate) |          1041.2 |            168.3 |     -83.8% |          1103.5 |            173.1 | -84.3% | pass; one dispatcher                             |
| **Total hook p50**             |    **1734.092** |     **1312.186** | **-24.3%** |               — |                — |      — | local improvement                                |

The candidate benchmark reports Stop allow p50/p95 `82.032/85.365 ms` and
objective-failure p50/p95 `86.306/87.701 ms`; each objective failure produced
seven historical benchmark blocks because the old case exercises the full
fixture matrix, while the consolidated dispatcher itself remains one process.
The continuation-budget and objective-gate tests are the authority for loop
semantics.

## Context, persistence, and maintenance

| Measure                               |                   Baseline |            Candidate | Delta / note              |
| ------------------------------------- | -------------------------: | -------------------: | ------------------------- |
| Total visible stdout chars            |                       2704 |                 2704 | unchanged                 |
| Estimated context units               |                        676 |                  676 | unchanged local heuristic |
| Hook cost score                       |                   3086.092 |             2664.186 | -13.7% local proxy        |
| Successful PostToolUse stdout         |                          0 |                    0 | contract preserved        |
| Successful Stop stdout                |                          0 |                    0 | contract preserved        |
| Candidate SessionStart startup output | unavailable in old section | 135–156 B by profile | profile budget respected  |
| Candidate SessionStart compact output | unavailable in old section |  93–114 B by profile | no heavy child process    |

Deferred maintenance remains a separate timing domain. The Phase 15 benchmark
keeps runner timing outside interactive p50/p95 and reports
`subscription_usage_measured=false`.

## Scenario and quality matrix

The legacy baseline executable exposes only its original lifecycle fixtures, so
the matrix distinguishes direct runtime evidence from deterministic quality
evidence rather than inventing baseline timings.

| Scenario                  | Runtime evidence                | Quality/evidence check                              | Result                                 |
| ------------------------- | ------------------------------- | --------------------------------------------------- | -------------------------------------- |
| small_read_only           | PreToolUse lifecycle            | read-only command remains allowed                   | PASS                                   |
| small_edit                | PostToolUse lifecycle shape     | apply_patch/file-line and shaping fixtures          | PASS                                   |
| medium_edit_test          | PostToolUse lifecycle shape     | large edit plus test-gate fixtures                  | PASS                                   |
| repeated_prompt           | prompt/continuity cases         | cache/task-signature tests                          | PASS; baseline cache field unavailable |
| session_start_startup     | candidate source/profile matrix | scoped startup continuity                           | PASS                                   |
| session_start_compact     | candidate source/profile matrix | compact delta and no dream child                    | PASS                                   |
| stop_allow                | candidate direct case           | empty stdout and no linguistic block                | PASS                                   |
| stop_objective_failure    | candidate direct case           | objective evidence creates one bounded continuation | PASS                                   |
| subagent_route            | Subagent lifecycle              | bounded router/advisor eval                         | PASS                                   |
| sensitive safety boundary | safety fixture and memory tests | local-only routing, no persisted body               | PASS                                   |

Quality evidence was deterministic: the new structural gate tests (4), routing
and profile/agent tests, MCP canonicalization tests, Stop and SessionStart
dispatch tests passed (`52 passed` in the focused Phase 16 set). The complete
repository and hook/memory validation commands are recorded in the checkpoint.
The seven-iteration bounded routing eval reports first-pass success `1.0`,
`max_threads=2`, `max_depth=1`, and two permitted high-complexity jobs (one per
fixture); it does not claim model answer quality.

## Validation ledger

| Check                   | Result                          | Interpretation                                                                        |
| ----------------------- | ------------------------------- | ------------------------------------------------------------------------------------- |
| `pytest tests -q`       | `941 passed, 5 subtests`        | local repository hard gate                                                            |
| hook test script        | `ALL_HOOK_TESTS_PASS`           | hook contracts and safety fixtures                                                    |
| repository doctor       | `DOCTOR_PASS`                   | candidate configuration is coherent                                                   |
| minimal gates           | `1 passed, 2 skipped, 0 failed` | gate runner passed with temporary report directory                                    |
| memory flow validation  | `PASS`                          | recall, scope, injection, persistence safety                                          |
| runtime structural gate | `passed`                        | 25 baseline handlers to 13 candidate handlers; no increase                            |
| global smoke/doctor     | known pre-existing failure      | stable installed checkout lacks the later lifecycle sources; no install was attempted |

The official benchmark comparator was also run. It returned exit status 2 with
`cambio no comparable` because the historical baseline has no `schema_version`;
this is retained as a visible compatibility finding rather than converted to a
zero or an invented delta.

## Gates and target verdicts

`python3 scripts/gates/runtime_optimization_gate.py --candidate-root ...
--baseline-root ...` returned `status=passed`. It enforces handler-count
non-increase, instruction hard cap, required invariants, `max_threads=2`,
`max_depth=1`, active MCP uniqueness, and the continuation cap. The baseline
intentionally fails those structural checks (`AGENTS` size, four threads, and
active MCP duplicates); the candidate has no structural errors.
With `--baseline-benchmark` and `--candidate-benchmark`, the same gate delegates
to the schema-aware comparator and fails on either a regression above the
configured noise threshold or an incompatible report.

| Target                                    | Verdict                                                 |
| ----------------------------------------- | ------------------------------------------------------- |
| PostToolUse reduction ≥70%                | PASS (-70.8% p50, -71.0% p95)                           |
| Stop one handler and no phrase-only block | PASS by structure/tests                                 |
| Stop p95 bound                            | PASS (`173.1 ms` aggregate, below the local bound)      |
| SessionStart child count 0 fast path      | PASS in candidate session matrix                        |
| SessionStart p95 bound                    | PASS (`55.106 ms` maximum candidate source/profile row) |
| MCP duplicate endpoints/schemas           | PASS                                                    |
| `max_threads=2`, `max_depth=1`            | PASS                                                    |
| `AGENTS.md ≤14 KiB`                       | PASS (`14,179` bytes)                                   |
| UserPromptSubmit one handler              | NOT MET on this branch; no change made in Phase 16      |
| PreToolUse one handler                    | NOT MET on this branch; no change made in Phase 16      |
| No subscription-credit claim              | PASS; flag remains false                                |

## Limitations and next boundary

- The old baseline JSON is schema-incompatible; the report does not claim a
  fake apples-to-apples value for fields it cannot provide.
- This comparison does not start MCP servers, make network calls, or inspect a
  real account. Quality fixtures do not measure model answer quality.
- The pre-existing installed global checkout still lacks the later lifecycle
  sources; no global install or user-level configuration write was performed.
- Phase 16 stopped after measurement and gating. No Phase 17 or SOL review was
  started.
