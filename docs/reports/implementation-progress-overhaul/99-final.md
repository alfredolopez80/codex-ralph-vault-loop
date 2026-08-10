# Implementation progress overhaul — final local release-candidate report

Date: 2026-08-10

Branch: `codex/implementation-progress-overhaul`

Worktree: `/Users/alfredolopez/Documents/GitHub/codex-ralph-progress-overhaul`

Executor constraint: `gpt-5.6-luna/max` only

Verdict: **RELEASE_CANDIDATE_PASS (local hardening and remote CI green)**

## Base and head SHAs

| Item                              | SHA                                                         |
| --------------------------------- | ----------------------------------------------------------- |
| `origin/main`                     | `92255e7d28a3bc84a005951957c953301ba40d7d`                  |
| merge base                        | `92255e7d28a3bc84a005951957c953301ba40d7d`                  |
| implementation hardening head     | `9e19744` (`fix: give task boundaries unique cache epochs`) |
| branch relation at hardening head | 18 commits ahead of `origin/main`                           |
| final published head              | `8dff84a` (`docs: record final task-boundary hardening`)    |

The report and PR draft are the final documentation artifacts for this
implementation head. The implementation SHA above is the exact code tree
reviewed by the hardening matrix; the published head records the documentation
that binds the remote CI result to that tree.

## Architecture before and after

Before the overhaul, implementation progress was split across legacy HTML
notes, schema-v2 indexes, Markdown/consolidated views, checkpoints, and
hook-local readers. Selection could cross worktree boundaries, retries could
re-read or rewrite derived artifacts, and auxiliary JSON/JSONL writers did not
share one bounded no-follow/atomic-publication contract.

After the overhaul, one bounded JSON/JSONL store under the primary checkout is
authoritative. A verified append-first journal reduces into `state.json`; the
manifest is discovery-only; operation IDs are plan-scoped and
idempotent/conflict-aware; sequence/hash links and cursors are checked before
mutation; partial tails and future schemas fail closed. SessionStart owns
epoch-aware recovery context through a content-free ledger. Prompt,
PostToolUse, and Stop are cache-first/local, with no implicit legacy-view
writes. Migration and rollback are explicit, locked, staged maintenance
commands. Auxiliary runtime writers use bounded reads/writes,
`O_NOFOLLOW`, regular/singly-linked checks, complete-write loops, atomic
publication, and directory `fsync`.

## Independent adversarial review and fixes

The fresh pass reviewed the entire branch diff against the actual merge base
and exercised path traversal, symlink/hardlink aliasing, TOCTOU and lock
ordering, permissions and atomic publication, operation-ID scope/conflicts,
journal sequence/hash/checksum handling, partial tails, future-schema
downgrade/overwrite, cross-repository/worktree/session/ambiguous selection,
context-epoch replay/suppression, RED/raw-body leakage, model provenance,
progress-maintenance routing, Stop false allow/block behavior, migration
loss/duplicates/orphans, rollback parity, bounded diagnostics, hidden view
writes, recursive scans, and cache-hit writes.

The validated Codex review threads were closed as follows:

- repeated task boundaries receive a unique content-free cache epoch before
  route reinitialization, so concurrent or identical boundaries cannot share a
  claim;
- active and reopened plans are discoverable through validation and Stop, while
  completion requires a non-empty canonical all-pass validation map;
- registration preflights manifest capacity under plan+manifest locks and
  stale publication cannot regress the event sequence;
- direct `mypy`/`ruff`/`tsc`/`uv`/`npx` runners reach structured validation;
- rollback snapshots and restores already-published targets and rejects
  fixed-name outputs overlapping canonical plan sources;
- implicit export persistence reports `PERSISTED=true` accurately;
- RED checkpoint rejection metrics reflect the actual bounded append;
- cost-ledger tool labels are redacted/bounded before persistence;
- terminal-business retention follows a monotonic claim sequence, and
  malformed marker bytes remain in place for explicit recovery.

Hash chains prove ordering and accidental tampering, not signatures against a
local writer able to rewrite every byte. Model provenance is content-free
platform evidence, not cryptographic executor attestation.

## Exact files changed versus `origin/main`

The exact 103-path manifest at the implementation hardening head is:

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
docs/reports/implementation-progress-overhaul/99-final.md
docs/reports/implementation-progress-overhaul/PR-DRAFT.md
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
tests/integration/test_prompt_sol_subagent_lifecycle_e2e.py
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

## Hard-gate ledger

| Gate                                                                      | Result                                                                                      |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q`             | **PASS — 1140 passed, 5 subtests, 172.10 s**                                                |
| `bash .codex/tests/run-hook-tests.sh`                                     | **PASS — ALL_HOOK_TESTS_PASS**                                                              |
| `bash scripts/validate-ralph-memory-flow.sh`                              | **PASS — 30 memory unit, 2 integration, 6 write-safety; ruff/mypy unavailable and skipped** |
| `python3 scripts/gates/run-gates.py --minimal`                            | **PASS — failed 0, passed 1, skipped 2**                                                    |
| `python3 scripts/setup/smoke-global-hooks.py`                             | **PASS — stable source marker observed**                                                    |
| `bash scripts/setup/doctor-global.sh`                                     | **PASS — warnings 0**                                                                       |
| `git diff --check`                                                        | **PASS**                                                                                    |
| Python compilation of changed runtime modules                             | **PASS**                                                                                    |
| Focused hardening suite                                                   | **PASS — 134 passed**                                                                       |
| Focused migration/store/context/routing/no-op/concurrency/installed suite | **PASS — 155 passed**                                                                       |
| Remote PR checks at `8dff84a`                                             | **PASS — test, CodeQL, Python, JS/TS, Actions**                                             |

Global smoke/doctor intentionally observed the existing installed source
marker at `/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop`.
That installed-source mismatch/topology is expected evidence for this local
worktree; no global file was modified.

## Baseline and candidate metrics

The deterministic Luna/Max canary used temporary repositories, linked
worktrees, HOME/RALPH_HOME roots, hook state, and sentinels only:

| Metric                                         |                   Candidate result | Verdict       |
| ---------------------------------------------- | ---------------------------------: | ------------- |
| Required canary scenarios                      |                              20/20 | PASS          |
| Feature fast-path p95                          |                           0.066 ms | PASS (≤5 ms)  |
| Recovery-path p95                              |                           0.068 ms | PASS (≤20 ms) |
| Luna full/delta maximum                        |                      242 B / 238 B | PASS          |
| Ordinary / unchanged continuation bytes        |                          0 B / 0 B | PASS          |
| Material publication                           |           1 append + 1 replacement | PASS          |
| Concurrent sequences                           |           1, 2, 3; hashes verified | PASS          |
| Automatic derived-view writes                  |                                  0 | PASS          |
| Recursive runtime byte scans                   |                                  0 | PASS          |
| Feature model/worker/advisor/MCP/network calls |                  0 / 0 / 0 / 0 / 0 | PASS          |
| Artifact reduction                             | 99.6% (3174 B vs 785672 B fixture) | PASS          |
| Store benchmark material p50/p95               |                 14.883 / 22.858 ms | observation   |
| Store benchmark unchanged p50/p95              |                 13.516 / 21.400 ms | observation   |
| Provider calls                                 |                                  0 | PASS          |

The Phase 0 aggregate comparison is `UNKNOWN/INCOMPATIBLE`: baseline schema 1
and candidate schema 2 are not safely comparable. The raw 1007-versus-312
context-unit values are not provider/account/subscription usage or savings.

## Migration and rollback proof

Deterministic migration fixtures discovered two approved plans, imported six
events, preserved source bytes and mtimes, imported one loose commit, and
imported zero duplicates on rerun. Focused tests cover partial interruption and
resume, divergent copies, duplicate operations, checksum/future-schema
blocking, bounded reads, orphan evidence, selective rollback preserving global
views, injected multi-target publication failure with restoration, and
canonical-source output collision blocking. Rollback source/output digests
match, the canonical journal/state remains unchanged, and malformed/future
schema evidence is preserved for explicit recovery.

No real local `.ralph/plans` data was read for migration or rollback apply.

## Privacy and model-routing proof

All validation and canary runs were local. Progress-maintenance has an explicit
zero Terra/Sol/advisor/worker/MCP allowance; feature model, worker, advisor,
MCP, and network sentinels stayed at zero. Model family/source/verified fields
are bounded provenance labels only. RED bodies are rejected or redacted before
persistence; cost-ledger tool labels are redacted/bounded, and RED checkpoint
rejection events report truthful bounded append metrics without storing the
rejected body. Runtime reports/quarantine retain only bounded codes, counts, and
digests. Cache hits, ordinary continuation, and unchanged Stop retries perform
zero business writes. No real provider-usage CSV/JSON was found; optional
`--usage` remains operator-supplied and `verified=false`.

## Limitations and known residuals

- Provider/account/subscription usage and monetary savings are not observable;
  absence of a real usage export is unknown, not zero.
- Whole-dispatcher comparison versus Phase 0 is schema-incompatible and
  scheduler-sensitive; hook p95 is observational.
- Hash chains prove local ordering/integrity but are not signatures against a
  local writer able to rewrite every byte.
- The installed global source remains the separate vault-loop checkout; this
  branch was not globally installed or switched on.
- Real-user-data migration, recovery-mode migration, hook registration cutover,
  merge, and deployment remain separate approval-boundary actions.
- Sol/unknown values are deterministic budget fixtures; no Sol executor ran.

## Explicit action boundary

The existing PR #72 was prepared as a local draft and this branch may be
pushed for its review preview. No new PR was created or opened, no PR approval
or merge was performed, no global installation/switch was performed, and no
real-user-data migration was performed. Push is the only external publication
action authorized for this handoff; merge/deployment remain explicitly out of
scope.
