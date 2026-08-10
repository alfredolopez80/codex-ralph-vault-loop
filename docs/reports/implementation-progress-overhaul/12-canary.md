# Implementation progress overhaul — Luna-only project-local canary

Date: 2026-08-10

Source HEAD: `533fe5d0742ccaa26eb6a1f5e72a90a2389a2acc`

Branch: `codex/implementation-progress-overhaul`
Executor fixture: `gpt-5.6-luna/max`

## Verdict

**PASS for the project-local canary.** All 20 required scenarios passed in
fresh deterministic fixtures. Two comparison metrics remain explicitly
`UNKNOWN/INCOMPATIBLE`: the Phase 0 report is schema 1 while the candidate and
comparator are schema 2. No value is converted into a provider, account, or
subscription savings claim.

No global installation was performed. No real-user `.ralph/plans` data was
read or migrated.

## Isolation and sentinels

The runner was
[`scripts/evals/implementation_progress_canary.py`](../../../scripts/evals/implementation_progress_canary.py).
Each fixture created a temporary Git repository, temporary `HOME`,
`RALPH_HOME`, `CODEX_HOOK_STATE_ROOT`, memory/vault roots, canonical and active
repository roots, and (where required) a linked worktree. All temporary roots
were removed when the runner exited.

The only model identity supplied to the runtime was the deterministic Luna
payload `gpt-5.6-luna` with effort `max`. Model, worker, advisor, MCP, and
network sentinels all remained at zero:

| Counter             | Observed |
| ------------------- | -------: |
| Feature model calls |        0 |
| Automatic workers   |        0 |
| Automatic advisors  |        0 |
| External MCP calls  |        0 |
| Network calls       |        0 |

Sentinel digests (the sentinel bodies are not stored in this report):

| Sentinel   | SHA-256                                                                   |
| ---------- | ------------------------------------------------------------------------- |
| plan       | `sha256:0527e2b364672c9d60c431ad497b559588bf78d58997f20b500e13cc14c66504` |
| prompt     | `sha256:5a0b8565389f26b7bf6cb6616db6592acd595abc855fcac9efc46abe4dfe8620` |
| model-call | `sha256:43b0d5ed37f24aae7ed31efd4408bdad363446fa0a810ad0df2368d186b150ea` |

## Required scenarios

|   # | Scenario                      | Evidence                                                         | Status |
| --: | ----------------------------- | ---------------------------------------------------------------- | ------ |
|   1 | Small planned implementation  | 3 ordered events; state remains `active`                         | PASS   |
|   2 | Multi-phase implementation    | 3 phase transitions; final phase `validation`                    | PASS   |
|   3 | Material decision             | 1 journal append + 1 state replacement                           | PASS   |
|   4 | Same operation retry          | `changed=false`, 0 bytes, state mtime unchanged                  | PASS   |
|   5 | Conflicting operation ID      | incompatible payload blocked; journal bytes preserved            | PASS   |
|   6 | Validation fail → pass        | both transitions material; final `tests=pass`                    | PASS   |
|   7 | Ordinary prompt               | progress output `0` bytes; reason `ordinary_or_reset`            | PASS   |
|   8 | Unchanged `continue`          | progress output `0` bytes; reason `same_session_writer`          | PASS   |
|   9 | New session                   | one full capsule, 242 bytes                                      | PASS   |
|  10 | Resume                        | one delta capsule, 227 bytes                                     | PASS   |
|  11 | Compact, unchanged generation | one 242-byte full capsule; retry 0 bytes and ledger hit          | PASS   |
|  12 | External generation change    | one 238-byte delta capsule                                       | PASS   |
|  13 | Ambiguous active plans        | no capsule and no context-ledger write                           | PASS   |
|  14 | Corrupt/future progress state | both rejected with source bytes preserved                        | PASS   |
|  15 | Concurrent writers            | two processes; ordered sequences `1,2,3`; hashes verified        | PASS   |
|  16 | Terminal Stop retry           | first completion changed 3 canonical files; retry changed 0      | PASS   |
|  17 | Linked worktree removal       | linked checkout removed; canonical state and validation survived | PASS   |
|  18 | Legacy fallback               | one bounded HTML parse; 211-byte recovery capsule                | PASS   |
|  19 | Migration dry-run/apply/rerun | 2 plans, 6 imported events, rerun imported 0                     | PASS   |
|  20 | Rollback export               | dry-run/apply output digests equal; new journal retained         | PASS   |

The focused migration suite also covers partial-apply interruption/resume,
divergent copies, duplicate operation IDs, checksum/future-schema blocking,
and source-byte preservation.

## Migration inventory evidence

The canary dry-run used nested deterministic legacy evidence and a schema-v2
index. It did not write the canonical store until the explicit apply step.

| Inventory item                                         |                                                                                                Observed |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------: |
| Approved plans / expected new IDs                      |                                                                2: `nested/index-only`, `nested/migrate` |
| Per-plan HTML notes                                    |                                                           1: `nested/migrate-implementation-notes.html` |
| Worktree roots inspected                               | 1 (the linked-worktree topology is separately exercised by scenario 17 and the focused migration suite) |
| Schema-v2 index plans / events / loose commits         |                                                                                               2 / 3 / 1 |
| Index Markdown                                         |                                                                               `implementation-index.md` |
| Consolidated views                                     |                        `implementation-notes-consolidated.html`, `implementation-notes-consolidated.md` |
| Conflicts / aliases / corrupt schemas / future schemas |                                                                                           0 / 0 / 0 / 0 |
| Missing plans / orphan views                           |                                                                                                   0 / 0 |
| Warnings                                               |                                                1: approved `nested/index-only` has no legacy HTML notes |

Expected state reductions were recorded before apply:

| Plan                | Expected events | Legacy bytes | Expected state bytes |                      Reduction |
| ------------------- | --------------: | -----------: | -------------------: | -----------------------------: |
| `nested/index-only` |               2 |            0 |                  910 | -910 (index-only plan warning) |
| `nested/migrate`    |               3 |        8,786 |                  998 |                          7,788 |

Apply verification preserved material fields and provenance. For
`nested/migrate`, the ordered operation IDs were:

```text
mig-281ceb1a533b6a1866c551ee635cf35287a4064f
legacy-op-1
legacy-op-2
```

The latest material event remained `legacy-op-2` with category `validation`,
status `completed`, timestamp `2026-08-10T00:00:00+00:00`, references
`README.md`, branch `canary-legacy`, commit `0123456789abcdef`, session
`legacy-session`, and a verified `sha256:` record hash. The loose commit was
imported to `unplanned-events.jsonl` and included in manifest verification.

The complete legacy plan tree had identical bytes and mtimes before and after
migration. The explicit rollback exporter ran only after dry-run validation;
it staged HTML/JSON/Markdown/consolidated outputs, reported source/output
digests, and never removed the new journal.

## Benchmark gates

The local runner measured the following. `estimated_context_units` are the
existing local `ceil(UTF-8 bytes / 4)` proxy, not tokens or credits.

| Gate                                      |                                                    Observed |  Target | Status               |
| ----------------------------------------- | ----------------------------------------------------------: | ------: | -------------------- |
| Feature model calls                       |                                                           0 |       0 | PASS                 |
| Automatic workers/advisors                |                                                           0 |       0 | PASS                 |
| Ordinary prompt progress                  |                                                         0 B |     0 B | PASS                 |
| Same-session unchanged continuation       |                                                         0 B |     0 B | PASS                 |
| Luna recovery capsule maximum             |                                                       242 B |  ≤512 B | PASS                 |
| Luna delta maximum                        |                                                       238 B |  ≤256 B | PASS                 |
| Sol/unknown fixture maximum               |                                                        81 B |   ≤96 B | PASS                 |
| Injection opportunities suppressed        |                                                  4/4 (100%) |    ≥90% | PASS                 |
| Aggregate estimated-context reduction     |                              312 vs 1,007 units; 69.02% raw |    ≥95% | UNKNOWN/INCOMPATIBLE |
| Normal-path HTML parses                   |                                                           0 |       0 | PASS                 |
| Legacy fallback parses                    |                                                           1 |      ≤1 | PASS                 |
| Same-session hot-path Git children        |                                                           0 |       0 | PASS                 |
| Cache-hit writes                          |                                                           0 |       0 | PASS                 |
| Unchanged business writes                 |                                                           0 |       0 | PASS                 |
| Material update publications              |                                    1 append + 1 replacement | ≤1 + ≤1 | PASS                 |
| Automatic Markdown/HTML/index writes      |                                                           0 |       0 | PASS                 |
| Recursive runtime byte scans              |                                                           0 |       0 | PASS                 |
| Implementation-artifact storage reduction |                99.6% (3,174 B vs 785,672 B Phase 0 fixture) |    ≥80% | PASS                 |
| Feature fast-path p95 contribution        |                                                    0.066 ms |   ≤5 ms | PASS                 |
| Recovery-path p95 contribution            |                                                    0.068 ms |  ≤20 ms | PASS                 |
| Whole-dispatcher p95 regression           | candidate aggregate p95 4,033.669 ms; baseline incompatible |    ≤10% | UNKNOWN/INCOMPATIBLE |
| Safety/quality regression                 |                                                           0 |       0 | PASS                 |

The existing dispatcher matrix was also run under isolated HOME with schema 2:
30 cases, p50/p95 aggregate `4,033.669/4,033.669 ms`, 5,718 output bytes,
1,430 estimated context units, 6 known child processes, 3 cache hits, and 0
advisors. These are local process measurements; they do not measure provider
latency, credits, account limits, or subscription usage.

## Schema-aware comparison

The checked-in comparator was used twice:

1. Phase 0 (`00-baseline.md`) is schema 1. The comparator rejected a direct
   Phase 0/candidate comparison as `unknown/incompatible` (exit 2), which is
   retained as an explicit limitation rather than silently normalizing it.
2. A deterministic schema-v2 repeated pair compared as `ruido` with no
   semantic changes, proving the comparator path and identity matching.

The Phase 0 aggregate of 1,007 estimated units and the candidate aggregate of
312 are therefore reported as raw local observations only. No provider or
account savings are inferred.

## Validation commands

```text
python3 -m py_compile scripts/evals/implementation_progress_canary.py
python3 scripts/evals/implementation_progress_canary.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
  tests/unit/test_progress_cli.py \
  tests/unit/test_implementation_store.py \
  tests/unit/test_implementation_notes_consolidator.py \
  tests/integration/test_legacy_migration.py \
  tests/integration/test_implementation_notes_workflow.py \
  tests/integration/test_implementation_notes_consolidation.py \
  tests/integration/test_implementation_notes_consolidation_security.py \
  tests/integration/test_progress_context_cli.py \
  tests/integration/test_progress_installed_dispatcher_e2e.py \
  tests/integration/test_progress_session_start_subprocess.py \
  tests/unit/test_implementation_index.py -q
```

Results: canary `PASS`; focused regression suite `114 passed`; Python compile
`PASS`; no global installation, push, PR, or real-user migration.

## Release-candidate hardening rerun

The independent hardening pass was validated from local `HEAD`
`40226c5afdc307b728618fd5a76883a9ea12543d` against base
`92255e7d28a3bc84a005951957c953301ba40d7d`, before the final release commit.
It reran the 20 deterministic scenarios with the same `gpt-5.6-luna/max`
fixture and added bounded auxiliary-file, partial-tail, future-schema, and
payload-approval checks. The canary remained `PASS` with zero model calls,
workers, advisors, MCP calls, and network calls.

| Measurement                        |                                     Candidate result | Verdict                  |
| ---------------------------------- | ---------------------------------------------------: | ------------------------ |
| Canary scenarios                   |                                                20/20 | PASS                     |
| Feature fast-path p95              |                                             0.065 ms | PASS (<=5 ms)            |
| Recovery-path p95                  |                                             0.066 ms | PASS (<=20 ms)           |
| Luna recovery / delta maximum      |                                        242 B / 238 B | PASS (<=512 B / <=256 B) |
| Ordinary / unchanged prompt bytes  |                                            0 B / 0 B | PASS                     |
| Material publication               |                             1 append + 1 replacement | PASS                     |
| Concurrent journal sequences       |                             1, 2, 3; hashes verified | PASS                     |
| Migration apply / rerun            |                       6 events / 0 duplicate imports | PASS                     |
| Rollback source/output digest      |                          equal; new journal retained | PASS                     |
| Store transaction p50 (20 samples) |                  18.533 ms material; 16.574 ms retry | PASS (local)             |
| Store transaction p95 (20 samples) |                  26.570 ms material; 25.234 ms retry | OBSERVATION              |
| Store transaction provider calls   |                                                    0 | PASS                     |
| Hook benchmark (5 + 1 warmup)      | p50 5279.106 ms; p95 5562.592 ms; 1430 context units | OBSERVATION              |
| Schema-aware Phase 0 comparison    |                 unknown/incompatible (schema 1 vs 2) | UNKNOWN, preserved       |

The hook benchmark is scheduler/process sensitive and remains a local
observation; it does not measure provider latency, account limits, credits, or
subscription usage. The schema-incompatible aggregate comparison is not
normalized into a savings claim.
