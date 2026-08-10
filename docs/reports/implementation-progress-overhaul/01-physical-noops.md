# Physical no-op phase report

- Phase: `physical-noops`
- Captured at: `2026-08-09T20:50:13+00:00`
- Pre-phase implementation SHA: `6640f907f1b5a280f99dc4f0ecdd76fb3aedd035`
- Comparison base: `92255e7d28a3bc84a005951957c953301ba40d7d`
- Status: `PASS`

This phase changes only the existing prompt-context cache, generic checkpoint
publication, the PostTool checkpoint event wrapper, and the runtime metadata
write guard. It does not add the new progress store.

## Commands and fixture

- `git status --short`, `git branch --show-current`, `git rev-parse HEAD`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_context_delta.py tests/unit/test_checkpoint_basic.py tests/unit/test_session_start_dispatch.py tests/unit/test_post_tool_dispatch.py tests/unit/test_user_prompt_dispatch.py tests/integration/test_continuity_prompt.py tests/integration/test_post_tool_checkpoint.py tests/integration/test_hook_config_lockstep.py tests/integration/test_hooks_basic.py -q`
- `bash scripts/validate-ralph-memory-flow.sh`
- `bash .codex/tests/run-hook-tests.sh`
- `python3 scripts/setup/smoke-global-hooks.py`
- `bash scripts/setup/doctor-global.sh`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_hook_runtime_cost_benchmark.py -q`
- `python3 scripts/evals/implementation_progress_baseline.py` through its local
  `run_baseline(..., base_sha_override=...)` entry point, 5 samples × 2 repeats

Each measurement used a fresh synthetic repository and isolated temporary
`HOME`/`RALPH_HOME`. Fixture creation was outside timed regions. The fixture
stubs recall and intake locally and rejects non-Git subprocesses. No provider,
advisor, worker, MCP, network, or coding-model call was permitted. Reports
contain only labels, bounded counters, hashes, IDs, and byte counts; no prompts,
assistant responses, note bodies, tool bodies, secrets, customer data, or
absolute temporary paths are stored.

## Physical no-op evidence

The direct writer measurements below use byte equality, SHA-256 equality, file
size equality, and `mtime_ns` equality. The publication metadata is returned to
the caller and is not persisted.

| Operation                                  |                                         Before phase |                                                                After phase | Evidence                                                                                                      |
| ------------------------------------------ | ---------------------------------------------------: | -------------------------------------------------------------------------: | ------------------------------------------------------------------------------------------------------------- |
| Valid unchanged prompt cache hit           | 1 cache publication, 1 updated entry, non-zero bytes |                     `changed=false`, `bytes_written=0`, `files_written=[]` | cache bytes/hash/size/mtime unchanged; 16 concurrent hits all read-only                                       |
| Semantically unchanged checkpoint          | latest JSON + Markdown + archive + event publication | `changed=false`, `bytes_written=0`, `files_written=[]`, `status=unchanged` | all checkpoint bytes/hash/size/mtime unchanged; 16 concurrent updates produced 1 changed result and 15 no-ops |
| Derived `latest.md` on unchanged update    |                    rewritten/created by every update |                                                              not recreated | removing `latest.md` before a semantic repeat leaves it absent                                                |
| Repeated PostTool observation              |         archive publication on every changed command |                          latest JSON/Markdown/event only; `archived=false` | archive bytes and `mtime_ns` unchanged for a non-boundary observation                                         |
| Repeated PostTool checkpoint wrapper event |                             one event per invocation |                                       no wrapper event for `changed=false` | event JSONL bytes and `mtime_ns` unchanged                                                                    |
| Active-context project metadata            |        `project.json` rewritten during runtime setup |                                            identical metadata is read-only | identical metadata keeps bytes/hash/size/mtime unchanged                                                      |

One direct sanitized sample measured a material checkpoint publication as
`2355` bytes across `latest.json`, `latest.md`, one archive, and one event;
the repeated semantic update measured `0` bytes. The corresponding cache sample
measured `796` bytes for the initial claim, `982` bytes for finalize, and `0`
bytes for the valid hit. These are local storage bytes, not context units.

## Automatic context and recovery coverage

The existing full fixture was rerun after the change. Values are p50/p95 for
latency and p50 for integer counters; context units use the existing
`ceil(output UTF-8 bytes / 4)` heuristic. Persistence rows below describe the
cache/checkpoint storage boundaries; the privacy-safe runtime observability
append is a separate metric stream and is not a cache or checkpoint
publication.

| Case                            | Progress bytes | Hook context bytes | Estimated units | Latency p50/p95 ms | Notes bytes | HTML parses | Plan reads | Index reads | Git subprocesses | Files written | Bytes written | mtime changes |
| ------------------------------- | -------------: | -----------------: | --------------: | -----------------: | ----------: | ----------: | ---------: | ----------: | ---------------: | ------------: | ------------: | ------------: |
| ordinary prompt                 |              0 |                868 |             217 |        3.228/4.875 |           0 |           0 |          0 |           0 |                0 |             5 |          4031 |             0 |
| first continuation              |            616 |                616 |             154 |      44.105/51.949 |       34868 |           3 |          2 |           0 |                7 |             3 |          1361 |             0 |
| repeated unchanged continuation |              0 |                  0 |               0 |      36.367/43.210 |       17434 |           1 |          1 |           0 |                7 |             0 |             0 |             0 |
| changed notes hash              |            746 |                746 |             187 |      44.133/50.272 |       37316 |           3 |          2 |           0 |                7 |             2 |          1166 |             2 |
| new session                     |            616 |                616 |             154 |      44.419/48.481 |       34868 |           3 |          2 |           1 |                7 |             3 |          1345 |             0 |
| resume                          |              0 |                266 |              67 |        1.362/1.463 |           0 |           0 |          0 |           0 |                0 |             1 |          1082 |             1 |
| compact                         |              0 |                335 |              84 |        1.384/1.564 |           0 |           0 |          0 |           0 |                0 |             1 |          1083 |             1 |
| ambiguous active plans          |              0 |                  0 |               0 |      32.456/40.161 |           0 |           0 |          0 |           1 |                7 |             1 |           668 |             0 |
| explicit context request        |            616 |                616 |             154 |      46.849/51.088 |       34868 |           3 |          2 |           0 |                7 |             2 |          1098 |             2 |

The automatic output values are unchanged by this phase; the physical no-op
work is in the cache/checkpoint persistence paths.

## Write amplification and persistence coverage

| Case                        | Latency p50/p95 ms | Files | Bytes | Replacements | Appends | fsync-relevant publications | fsync calls | mtime changes | Recursive scans | Scan bytes |
| --------------------------- | -----------------: | ----: | ----: | -----------: | ------: | --------------------------: | ----------: | ------------: | --------------: | ---------: |
| create notes                |      75.500/82.387 |     5 | 12157 |            2 |       0 |                           2 |           4 |             0 |               0 |          0 |
| append material entry       |      72.805/81.618 |     3 | 15502 |            3 |       1 |                           3 |           6 |             3 |               0 |          0 |
| idempotent append retry     |      70.876/83.976 |     2 |  6173 |            2 |       0 |                           2 |           4 |             2 |               0 |          0 |
| checkpoint update           |        2.667/2.953 |     7 |  4662 |            3 |       0 |                           3 |           3 |             0 |               2 |       4662 |
| checkpoint unchanged update |        1.316/1.612 |     0 |     0 |            0 |       0 |                           0 |           0 |             0 |               2 |       9324 |
| prompt-context cache hit    |        0.807/1.013 |     0 |     0 |            0 |       0 |                           0 |           0 |             0 |               0 |          0 |
| Stop allow                  |      79.541/84.687 |     8 |  8834 |            2 |       0 |                           2 |           4 |             2 |               2 |       2201 |
| terminal Stop retry         |      78.655/87.907 |     4 |  8813 |            2 |       1 |                           2 |           4 |             4 |               2 |       7105 |

The full-tree Stop rows include generic handoff/continuation persistence and
remain outside this phase. The checkpoint row's recursive scans are existing
PostTool observer scans, not checkpoint publication; they remain a later-phase
target.

## Model/provider accounting

- Configured executor: `gpt-5.6-luna/max`.
- Actual external model calls: `0`.
- Actual advisor calls: `0`.
- Actual worker calls: `0`.
- Provider and subscription usage: `unknown` (unavailable locally, never
  converted to zero).

## Safety and compatibility gates

- TTL and bounded eviction remain based on the last material cache update;
  valid hits do not refresh TTL timestamps.
- Corrupt cache/checkpoint quarantine, scope checks, classification, RED
  suppression, permissions, symlink refusal, locking, atomic publication, and
  fail-open hook behavior remain covered by the existing suites.
- `latest.md` remains available as a compatibility-derived view on material
  publication; an unchanged update never publishes it.
- Archive retention is limited to status, classification, phase, objective,
  next-action, validation, blocker, or risk boundaries. Repeated observations
  update the rolling latest state and journal only.

## Focused validation and limitations

- Focused cache/checkpoint/PostTool/context/hook suites: `163 passed` across the
  final selected run; the dedicated no-op tests include concurrent writers.
- Hook runtime benchmark contract: `4 passed`; the resolved temporary fixture
  keeps runtime observability compatible with its symlink refusal.
- Ralph memory-flow validation: `PASS` (`30` memory unit, `2` fake integration,
  and `6` post-hook safety tests; shell lint passed).
- Hook smoke: `ALL_HOOKS_PASS`.
- Global smoke/doctor: `PASS`; no global files were installed or changed.
- The benchmark's latency is scheduler-sensitive; compare p50/p95 within the
  documented ±30% local noise bound. Integer I/O counters are expected to be
  exact for a fixed fixture.
- Provider/account usage is unavailable and remains `unknown`.
- The legacy benchmark still measures the existing recursive observer scans and
  generic Stop persistence; no claim is made that this phase meets the later
  store/scan/latency targets.

## Target deltas for the next phase

| Approved-plan target                            |                                         Before baseline |                This phase |
| ----------------------------------------------- | ------------------------------------------------------: | ------------------------: |
| Cache-hit durable writes                        |  2 files / 1612 bytes / 1 replacement / 2 mtime changes |             0 / 0 / 0 / 0 |
| Unchanged checkpoint business writes            | 6 files / 5505 bytes / 3 replacements / 6 mtime changes |             0 / 0 / 0 / 0 |
| Same-session unchanged continuation persistence |                     1 file / 667 bytes / 1 mtime change |                 0 / 0 / 0 |
| Provider/subscription accounting                |                                             unavailable |                 `unknown` |
| New progress store                              |                                             not present | intentionally not started |

The remaining HTML/plan/index reads, Git children, recursive scans, recovery
capsule sizing, and generic Stop persistence are deliberately carried into the
next approved phase rather than hidden behind this no-op gate.
