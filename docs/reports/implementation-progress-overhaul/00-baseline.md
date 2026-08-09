# Implementation-progress overhead baseline

- Schema: `1`
- Captured at: `2026-08-09T19:10:00+00:00`
- Current base SHA: `92255e7d28a3bc84a005951957c953301ba40d7d`
- `origin/main`: `92255e7d28a3bc84a005951957c953301ba40d7d`
- Status: `PASS` for measurement integrity; this is a legacy baseline, not a candidate improvement.

## Commands

- `git status --short`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git rev-parse origin/main`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_implementation_progress_baseline.py tests/unit/test_implementation_context_budget.py tests/unit/test_runtime_profile.py tests/unit/test_subagent_routing.py tests/unit/test_post_tool_dispatch.py tests/unit/test_stop_dispatch.py tests/integration/test_implementation_notes_context.py tests/integration/test_post_tool_checkpoint.py tests/integration/test_stop_handoff_checkpoint.py -q`
- `python3 scripts/evals/implementation_progress_baseline.py --output docs/reports/implementation-progress-overhaul/00-baseline.md`

## Fixture and privacy rules

- Each sample uses a fresh synthetic local Git repository and separate temporary `HOME`/`RALPH_HOME`.
- Fixture setup is outside timed regions; measured regions use existing implementation-progress functions.
- Prompt capture and memory recall are stubbed locally. No provider, advisor, worker, MCP, network, or non-Git subprocess is permitted.
- Reports contain labels, counters, hashes/IDs only; prompt text, note bodies, tool bodies, secrets, customer data, and absolute temporary paths are excluded.
- HTML parser, plan/index reader, atomic publication, cache, checkpoint, Stop, and recursive-scan counters are scoped to named current boundaries.

## Automatic context and recovery output

| Case                            | Progress bytes | Hook context bytes | Estimated units | Latency p50/p95 ms | Notes bytes | HTML parses | Plan reads | Index reads | Git subprocesses | Files written |          Bytes written | mtime changes |
| ------------------------------- | -------------: | -----------------: | --------------: | -----------------: | ----------: | ----------: | ---------: | ----------: | ---------------: | ------------: | ---------------------: | ------------: |
| ordinary_prompt                 |            0.0 |              827.0 |           207.0 |        4.196/6.321 |         0.0 |         0.0 |        0.0 |         0.0 |              0.0 |           5.0 | p50=3901.0; p95=3902.0 |           0.0 |
| first_continuation              |          616.0 |              616.0 |           154.0 |        54.72/57.53 |     34868.0 |         3.0 |        2.0 |         0.0 |              7.0 |           3.0 |                 1361.0 |           0.0 |
| repeated_unchanged_continuation |            0.0 |                0.0 |             0.0 |        47.407/52.3 |     17434.0 |         1.0 |        1.0 |         0.0 |              7.0 |           1.0 |                  667.0 |           1.0 |
| changed_notes_hash              |          746.0 |              746.0 |           187.0 |      55.299/60.839 |     37316.0 |         3.0 |        2.0 |         0.0 |              7.0 |           3.0 |                 1833.0 |           3.0 |
| new_session                     |          616.0 |              616.0 |           154.0 |      55.942/64.841 |     34868.0 |         3.0 |        2.0 |         1.0 |              7.0 |           3.0 |                 1345.0 |           0.0 |
| resume                          |            0.0 |              266.0 |            67.0 |        1.734/1.789 |         0.0 |         0.0 |        0.0 |         0.0 |              0.0 |           2.0 |                 1749.0 |           2.0 |
| compact                         |            0.0 |              335.0 |            84.0 |        1.781/1.923 |         0.0 |         0.0 |        0.0 |         0.0 |              0.0 |           2.0 |                 1750.0 |           2.0 |
| ambiguous_active_plans          |            0.0 |                0.0 |             0.0 |      42.343/47.712 |         0.0 |         0.0 |        0.0 |         1.0 |              7.0 |           1.0 |                  668.0 |           0.0 |
| explicit_context_request        |          616.0 |              616.0 |           154.0 |      53.991/58.963 |     34868.0 |         3.0 |        2.0 |         0.0 |              7.0 |           3.0 |                 1765.0 |           3.0 |

## Write amplification and persistence

| Case                        | Latency p50/p95 ms | Hook output bytes | Estimated units | Notes bytes | HTML parses | Plan reads | Index reads | Git subprocesses | Files written |          Bytes written | Replacements | Appends | fsync-relevant publications | fsync calls | mtime changes | Recursive scans |             Scan bytes |              Scan ms |
| --------------------------- | -----------------: | ----------------: | --------------: | ----------: | ----------: | ---------: | ----------: | ---------------: | ------------: | ---------------------: | -----------: | ------: | --------------------------: | ----------: | ------------: | --------------: | ---------------------: | -------------------: |
| create_notes                |     95.029/101.323 |               0.0 |             0.0 |     24327.0 |         3.0 |        2.0 |         0.0 |             12.0 |           5.0 |                12157.0 |          2.0 |     0.0 |                         2.0 |         4.0 |           0.0 |             0.0 |                    0.0 |                  0.0 |
| append_material_entry       |      93.715/98.416 |               0.0 |             0.0 |     27987.0 |         5.0 |        0.0 |         1.0 |             12.0 |           3.0 |                15502.0 |          3.0 |     1.0 |                         3.0 |         6.0 |           3.0 |             0.0 |                    0.0 |                  0.0 |
| idempotent_append_retry     |       94.196/98.51 |               0.0 |             0.0 |     27987.0 |         5.0 |        0.0 |         1.0 |             12.0 |           2.0 |                 6173.0 |          2.0 |     0.0 |                         2.0 |         4.0 |           2.0 |             0.0 |                    0.0 |                  0.0 |
| checkpoint_update           |        4.249/4.757 |               0.0 |             0.0 |         0.0 |         0.0 |        0.0 |         0.0 |              0.0 |           7.0 |                 4662.0 |          3.0 |     0.0 |                         3.0 |         3.0 |           0.0 |             2.0 |                 4662.0 | p50=0.258; p95=0.358 |
| checkpoint_unchanged_update |        2.924/3.183 |               0.0 |             0.0 |         0.0 |         0.0 |        0.0 |         0.0 |              0.0 |           6.0 |                 5505.0 |          3.0 |     2.0 |                         3.0 |         3.0 |           6.0 |             2.0 |                10167.0 | p50=0.402; p95=0.471 |
| prompt_context_cache_hit    |        1.269/1.536 |               0.0 |             0.0 |         0.0 |         0.0 |        0.0 |         0.0 |              0.0 |           2.0 | p50=1612.0; p95=1613.0 |          1.0 |     0.0 |                         1.0 |         1.0 |           2.0 |             0.0 |                    0.0 |                  0.0 |
| stop_allow                  |     98.404/108.617 |               0.0 |             0.0 |     34868.0 |         4.0 |        0.0 |         1.0 |             12.0 |           8.0 | p50=8834.0; p95=8837.0 |          2.0 |     0.0 |                         2.0 |         4.0 |           2.0 |             2.0 | p50=2201.0; p95=2204.0 | p50=0.284; p95=0.387 |
| terminal_stop_retry         |    101.539/113.635 |               0.0 |             0.0 |     34868.0 |         4.0 |        0.0 |         1.0 |             12.0 |           5.0 | p50=9480.0; p95=9483.0 |          2.0 |     1.0 |                         2.0 |         4.0 |           5.0 |             2.0 | p50=7105.0; p95=7113.0 |  p50=0.55; p95=0.634 |

## Model and provider accounting

- Configured executor: `gpt-5.6-luna/max`.
- Actual external model calls observed: `0`.
- Actual advisor calls observed: `0`.
- Actual worker calls observed: `0`.
- Provider/subscription accounting: `unknown` / `unknown`.
- The zero call counts are measured fixture facts; unavailable provider usage is deliberately `unknown`, never coerced to zero.

## Exact target deltas from the approved plan

| Target                                    |                 Required |                                            Baseline observation | Status/delta                                |
| ----------------------------------------- | -----------------------: | --------------------------------------------------------------: | ------------------------------------------- |
| Feature model calls                       |                        0 |                                                               0 | PASS                                        |
| Automatic advisors/workers                |                        0 |                                                           0 / 0 | PASS                                        |
| Ordinary progress context                 |                  0 bytes |                                                       0.0 bytes | PASS                                        |
| Same-session unchanged continuation       |                  0 bytes |                                                       0.0 bytes | PASS                                        |
| Luna recovery capsule                     |              <=512 bytes |                                                     616.0 bytes | +104 bytes over target                      |
| Luna delta capsule                        |              <=256 bytes |                                                     746.0 bytes | +490 bytes over target                      |
| Sol/unknown automatic progress            |               <=96 bytes |                                     unknown (Luna-only fixture) | unknown                                     |
| Automatic injection suppression           |                    >=90% | unknown (opportunity denominator is not exposed by legacy path) | unknown                                     |
| HTML parses on new normal path            |                        0 |                                                             3.0 | +3 parses over target                       |
| Git children on hot continuation          |                        0 |                                                             7.0 | +7 git children over target                 |
| Cache-hit durable writes                  |                        0 |                                                             2.0 | +2 files over target                        |
| Unchanged checkpoint/Stop business writes |                        0 |                                                       6.0 / 5.0 | +6 files over target / +5 files over target |
| Recursive runtime scans                   |                        0 |                                                       2.0 / 2.0 | +2 scans over target / +2 scans over target |
| Material update publication               | <=1 journal + 1 snapshot |                                                3.0 replacements | +1 replacement over target                  |
| Automatic Markdown/HTML/index view writes |                        0 |                                                             3.0 | +3 files over target                        |
| Feature fast-path p95                     |                   <=5 ms |                                                            52.3 | +47.3 ms over target                        |
| Recovery p95                              |                  <=20 ms |                                                           1.789 | PASS                                        |
| Whole-dispatcher p95 regression           |                    <=10% |                                         unknown until candidate | unknown                                     |
| Persistent implementation bytes           |          >=80% reduction |                                         unknown until candidate | unknown                                     |
| Existing safety/quality regression        |                        0 |                                  unknown until candidate suites | unknown                                     |

## Reproducibility and limitations

- Samples: `5` per case across `2` repeat(s).
- Noise bound: latency p50/p95 is local-process timing; compare repeated runs within +/-30%; integer I/O counters must match exactly.
- Focused repeat verification: `68/68` exact-counter checks were consistent across two repeats; no varied counters were observed.
- Integer I/O counters are expected to be exact for the same fixture and code; latency is scheduler-sensitive and is compared by p50/p95.
- Provider, subscription, and account usage are unavailable locally; they remain unknown rather than zero.
- Estimated context units use the existing ceil(output UTF-8 bytes / 4) heuristic and are not tokens or credits.
- Fixture uses one synthetic primary checkout; linked-worktree topology is not claimed by this baseline.
- Bytes-written estimates are full-file sizes for changed files; named atomic boundaries additionally report publication bytes and fsync-relevant calls.
- Latency excludes fixture creation and Git setup; it includes only the measured existing operation.
- Runtime scans are measured at the current PostToolUse/Stop directory_bytes boundaries and are not reproduced by an extra observer scan.

## Follow-up comparison contract

- Later phases must compare these same case names and distinguish local storage bytes, CPU/I/O latency, estimated context units, and provider/account usage.
- A candidate cannot claim the plan's 0-byte/0-parse/0-scan/no-op targets from a missing measurement; missing values remain `unknown`.
