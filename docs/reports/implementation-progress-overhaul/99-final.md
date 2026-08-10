# Implementation progress overhaul — final local release-candidate report

Date: 2026-08-10

Branch: `codex/implementation-progress-overhaul`

Worktree: `/Users/alfredolopez/Documents/GitHub/codex-ralph-progress-overhaul`

Executor constraint: `gpt-5.6-luna/max` only
Verdict: **RELEASE_CANDIDATE_PASS (local, not installed)**

## Base and head

The independent fresh-pass review used the actual `origin/main` merge base and
the branch head before the final release commit:

| Item                  | SHA                                        |
| --------------------- | ------------------------------------------ |
| `origin/main`         | `92255e7d28a3bc84a005951957c953301ba40d7d` |
| merge base            | `92255e7d28a3bc84a005951957c953301ba40d7d` |
| audited branch `HEAD` | `40226c5afdc307b728618fd5a76883a9ea12543d` |
| branch relation       | 12 commits ahead of `origin/main`          |

The audited tree includes the uncommitted hardening and documentation changes
listed below; the final conventional commit records that exact tree. The
final commit SHA is reported by Git after commit and in the handoff response.

## Architecture before and after

Before this overhaul, implementation progress was distributed across legacy
HTML notes, schema-v2 indexes, Markdown/consolidated views, checkpoints, and
hook-local readers. Selection could cross worktree boundaries, retries could
re-read or rewrite derived artifacts, and several auxiliary JSON/JSONL writers
had no uniform no-follow, size, or atomic-publication contract.

After this overhaul, one bounded JSON/JSONL implementation store under the
primary checkout is authoritative. State is reduced from a verified,
append-first journal; the manifest is discovery-only; plan-scoped operation IDs
are idempotent/conflict-aware; sequence and hash links are checked before
mutation; partial tails and future schemas fail closed. SessionStart owns
recovery context, with epoch/generation/capsule keys in a content-free ledger.
Prompt/PostToolUse/Stop are cache-first and local, and ordinary lifecycle paths
never publish legacy HTML/Markdown/index views. Migration and rollback are
explicit, locked, staged maintenance commands. Auxiliary runtime files now
share bounded reads/writes, `O_NOFOLLOW`, regular/single-link checks, complete
write loops, atomic same-directory publication, and directory `fsync`.

## Independent adversarial review and fixes

The fresh pass reviewed the full branch diff against the base and exercised:

- traversal, symlink, hardlink, TOCTOU, lock aliasing, primary-checkout and
  linked-worktree selection;
- permissions, atomic publication, short writes, crash points, partial tails,
  journal sequence/hash validation, operation-ID conflicts, and future-schema
  downgrade/overwrite attempts;
- context epoch replay/suppression, ambiguous plans, cross-session and
  cross-repository selection, payload approval spoofing, model-provenance
  boundaries, RED/raw-body handling, and maintenance routing;
- Stop false allow/block behavior, migration duplicate/orphan/loss handling,
  rollback parity, bounded diagnostics, cache-hit writes, hidden view writes,
  and recursive runtime scans.

Validated findings were fixed in the tree. In particular, mutating replay now
rejects an incomplete final JSONL line; future-schema reads are typed blocking
results and preserve source bytes; payload approval booleans cannot approve an
undocumented plan; foreign stores and worktree roots are rejected; Stop does
not complete progress when an independent hard finding exists; and the new
Stop path no longer writes legacy implementation-note/index views. Runtime
observability inputs, quarantine records, report groups, outputs, hook stdin,
compatibility stdout, queues, caches, ledgers, checkpoints, handoffs, and
learning writes are bounded. The protected macOS `/var` and `/tmp` aliases are
accepted only when they resolve to the kernel-owned `/private` targets; user
symlinks remain rejected.

Hash chains provide ordering and accidental-tamper evidence, not signatures
against a local attacker who can rewrite every record. Model provenance fields
are content-free platform labels, not cryptographic executor attestation.

## Exact branch files changed versus `origin/main`

The branch diff contains these 99 files:

```text
.agents/skills/ralph-plan-implementation-notes/SKILL.md
.codex/hooks/continuity_prompt_context.py
.codex/hooks/global_hook_dispatch.py
.codex/hooks/implementation_notes_guard.py
.codex/hooks/post_tool_checkpoint.py
.codex/hooks/post_tool_dispatch.py
.codex/hooks/post_tool_extract_memory.py
.codex/hooks/pre_tool_dispatch.py
.codex/hooks/session_start_dispatch.py
.codex/hooks/shared/active_context.py
.codex/hooks/shared/agent_budget.py
.codex/hooks/shared/checkpoint_io.py
.codex/hooks/shared/context_delta.py
.codex/hooks/shared/continuation_budget.py
.codex/hooks/shared/implementation_store/__init__.py
.codex/hooks/shared/implementation_store/io.py
.codex/hooks/shared/implementation_store/paths.py
.codex/hooks/shared/implementation_store/schema.py
.codex/hooks/shared/implementation_store/store.py
.codex/hooks/shared/maintenance_queue.py
.codex/hooks/shared/objective_gates.py
.codex/hooks/shared/paths.py
.codex/hooks/shared/persistence_metrics.py
.codex/hooks/shared/post_tool_ledger.py
.codex/hooks/shared/post_tool_state.py
.codex/hooks/shared/progress_hook.py
.codex/hooks/shared/progress_runtime.py
.codex/hooks/shared/prompt_context_components.py
.codex/hooks/shared/runtime_event_store.py
.codex/hooks/shared/runtime_observability.py
.codex/hooks/shared/runtime_profile.py
.codex/hooks/shared/session_context_cache.py
.codex/hooks/shared/sol_advisor.py
.codex/hooks/shared/stop_persistence.py
.codex/hooks/shared/subagent_routing.py
.codex/hooks/shared/task_signature.py
.codex/hooks/shared/vault_io.py
.codex/hooks/sol_advisor_pretool_guard.py
.codex/hooks/sol_advisor_prompt_state.py
.codex/hooks/stop_dispatch.py
.codex/hooks/stop_persist_memory.py
.codex/hooks/subagent_routing_pretool_guard.py
.codex/hooks/user_prompt_dispatch.py
docs/architecture/hooks.md
docs/architecture/implementation-progress-store.md
docs/codex-hooks.md
docs/guides/runtime-observability.md
docs/model-level-routing.md
docs/plans/implementation-notes.md
docs/reports/implementation-progress-overhaul/00-baseline.md
docs/reports/implementation-progress-overhaul/01-physical-noops.md
docs/reports/implementation-progress-overhaul/02-stop-noop-persistence.md
docs/reports/implementation-progress-overhaul/03-new-store-core.md
docs/reports/implementation-progress-overhaul/04-transaction-replay.md
docs/reports/implementation-progress-overhaul/05-cli-compatibility.md
docs/reports/implementation-progress-overhaul/06-unified-context.md
docs/reports/implementation-progress-overhaul/07-hook-integration.md
docs/reports/implementation-progress-overhaul/08-posttool-stop-integration.md
docs/reports/implementation-progress-overhaul/09-migration.md
docs/reports/implementation-progress-overhaul/12-canary.md
scripts/evals/hook_benchmark_scenarios.py
scripts/evals/implementation_progress_baseline.py
scripts/evals/implementation_progress_canary.py
scripts/evals/report_runtime_overhead.py
scripts/memory/wakeup.py
scripts/plans/append-implementation-note.py
scripts/plans/create-implementation-notes.py
scripts/plans/implementation_notes_lib.py
scripts/plans/legacy_compat.py
scripts/plans/legacy_migration.py
scripts/plans/progress.py
scripts/plans/progress_context.py
scripts/plans/read-implementation-context.py
scripts/plans/update-implementation-index.py
tests/benchmarks/implementation_store_transaction_benchmark.py
tests/integration/test_implementation_notes_context.py
tests/integration/test_legacy_migration.py
tests/integration/test_post_tool_checkpoint.py
tests/integration/test_progress_context_cli.py
tests/integration/test_progress_installed_dispatcher_e2e.py
tests/integration/test_progress_session_start_subprocess.py
tests/unit/test_active_context.py
tests/unit/test_agent_budget.py
tests/unit/test_checkpoint_basic.py
tests/unit/test_context_delta.py
tests/unit/test_implementation_progress_baseline.py
tests/unit/test_implementation_store.py
tests/unit/test_implementation_store_transactions.py
tests/unit/test_post_tool_dispatch.py
tests/unit/test_progress_cli.py
tests/unit/test_progress_context.py
tests/unit/test_progress_hook_integration.py
tests/unit/test_progress_runtime_integration.py
tests/unit/test_runtime_observability.py
tests/unit/test_runtime_profile.py
tests/unit/test_sol_advisor_hooks.py
tests/unit/test_stop_business_noop.py
tests/unit/test_subagent_routing.py
tests/unit/test_task_signature.py
```

The final release commit additionally adds this report and `PR-DRAFT.md`.

## Hard-gate ledger

| Gate                                                                       | Result                                                                                                       |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q`              | **PASS** — 1124 passed, 5 subtests, 181.95 s                                                                 |
| `bash .codex/tests/run-hook-tests.sh`                                      | **PASS** — `ALL_HOOK_TESTS_PASS`                                                                             |
| `bash scripts/validate-ralph-memory-flow.sh`                               | **PASS** — 30 memory unit, 2 integration, 6 write-safety; shellcheck pass; ruff/mypy unavailable and skipped |
| `python3 scripts/gates/run-gates.py --minimal`                             | **PASS** — failed 0, skipped 1 (security intentionally skipped in minimal mode)                              |
| `python3 scripts/setup/smoke-global-hooks.py`                              | **PASS**                                                                                                     |
| `bash scripts/setup/doctor-global.sh`                                      | **PASS** — warnings 0                                                                                        |
| `git diff --check`                                                         | **PASS**                                                                                                     |
| AST parse of all changed runtime modules                                   | **PASS**                                                                                                     |
| focused migration/store/context/routing/no-op/concurrency/installed suites | **PASS** — 172 passed                                                                                        |
| runtime observability + context-guard benchmark tests                      | **PASS** — 11 passed; acceptance 0.965517 >= 0.95                                                            |

Global smoke/doctor observed the already-installed stable source marker at
`/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop`, not this
worktree. That existing-source topology was left untouched as required; no
global install or source synchronization was performed.

## Benchmark verdict and metrics

The final deterministic Luna/Max canary ran in fresh temporary repositories,
HOME/RALPH_HOME roots, linked worktrees, hook-state roots, and sentinels:

| Metric                                         |                                               Result | Verdict        |
| ---------------------------------------------- | ---------------------------------------------------: | -------------- |
| Required canary scenarios                      |                                                20/20 | PASS           |
| feature fast-path p95                          |                                             0.065 ms | PASS (<=5 ms)  |
| recovery-path p95                              |                                             0.066 ms | PASS (<=20 ms) |
| Luna full/delta maximum                        |                                        242 B / 238 B | PASS           |
| ordinary / unchanged continuation bytes        |                                            0 B / 0 B | PASS           |
| material publication                           |                             1 append + 1 replacement | PASS           |
| concurrent sequences                           |                             1, 2, 3; hashes verified | PASS           |
| automatic derived-view writes                  |                                                    0 | PASS           |
| recursive runtime byte scans                   |                                                    0 | PASS           |
| implementation artifact reduction              |                   99.6% (3174 B vs 785672 B fixture) | PASS           |
| feature model/worker/advisor/MCP/network calls |                                    0 / 0 / 0 / 0 / 0 | PASS           |
| store transaction p50 (20 samples)             |                  18.533 ms material; 16.574 ms retry | PASS (local)   |
| store transaction p95 (20 samples)             |                  26.570 ms material; 25.234 ms retry | OBSERVATION    |
| hook benchmark (5 + 1 warmup)                  | p50 5279.106 ms; p95 5562.592 ms; 1430 context units | OBSERVATION    |
| context-guard acceptance                       |                             0.965517; threshold 0.95 | PASS           |

The Phase 0 aggregate comparison remains `UNKNOWN/INCOMPATIBLE` because the
baseline is schema 1 and the candidate is schema 2. The raw 1007-versus-312
context-unit observations are not normalized into provider, account, credit,
or subscription savings. Sol/unknown outputs are deterministic budget fixtures;
no Sol executor ran.

## Migration and rollback proof

The deterministic migration canary proved: two approved plans discovered; six
events imported; a rerun imported zero duplicates; legacy bytes and mtimes were
unchanged; source digests and record hashes verified; one loose commit remained
in `unplanned-events.jsonl`; and the linked-worktree removal scenario preserved
canonical state and validation. The focused migration suite also covered
partial-apply interruption/resume, divergent copies, duplicate operation IDs,
checksum/future-schema blocking, bounded source reads, and orphan evidence.

Rollback dry-run and apply produced equal source/output digests, validated
staged HTML/index/consolidated artifacts, retained the new journal/state, and
did not delete or rewrite canonical evidence. A future-schema Stop fixture
returned `progress_future_schema`, preserved the exact source bytes, and left
the journal at `started` only.

## Privacy and model-routing proof

All canary and focused runs were local. The feature model-call, worker,
advisor, MCP, and network sentinels stayed at zero. Progress-maintenance
routing has an explicit zero worker/advisor budget and does not call Terra,
Sol, an advisor, a worker, or an MCP. Model family/source/verified fields are
bounded provenance labels only. RED content is rejected or redacted before
persistence; runtime reports/quarantine retain only bounded codes, counts, and
digests, never raw prompt, tool, memory, note, or assistant bodies. Cache hits,
ordinary continuation, and unchanged Stop retries performed zero business
writes. Legacy views are explicit CLI/maintenance outputs, never hidden hook
writes.

## Limitations and known residuals

- Provider/account/subscription usage and monetary savings are not measured.
- Whole-dispatcher regression versus Phase 0 is schema-incompatible and
  scheduler-sensitive; the local hook benchmark is observational.
- Hash chains do not provide cryptographic signatures against a local writer
  who can rewrite every journal byte.
- The installed global hook source remains the separate vault-loop checkout;
  this candidate was not globally installed or switched on.
- Real local `.ralph/plans` migration, hook registration cutover, and recovery
  mode remain explicitly unauthorized and deferred to the next approval.
- Legacy compatibility writers and some optional provider/subscription
  accounting surfaces report `unknown` by design rather than fabricating zero.
- Sol/unknown profile numbers are deterministic budget fixtures, not executor
  measurements.

## Explicit non-actions

No global installation, push, PR creation/opening, merge, deployment, or
real-user-data migration was performed. The PR is prepared only as a local
draft in `PR-DRAFT.md`.
