# Evaluation Spine

The evaluation spine uses RASS v1 scorecards, hard gates, deterministic fixtures, JSON reports, and AutoResearch packet ledgers. Generated reports are written under `.ralph-codex/reports/evals`.

RASS v1 weights:

- Effectiveness: 35%.
- Efficiency: 20%.
- Reliability and safety: 20%.
- Memory and research quality: 15%.
- Maintainability and simplicity: 10%.

Hard gates include tests pass, no secret leak, eval files unchanged, no scope violation, and no eval gaming. A failed hard gate makes the result fail even when metric scores look strong. Scorecards may add stricter scorecard-specific hard gates; these are additive to the global gates and cannot replace or weaken the global set.

Current eval surfaces cover AutoResearch, research citation quality, vision analysis, coding model routing, memory retrieval, and cost routing.

Context discipline is measured by
`scripts/evals/context_guard_autoresearch_benchmark.py`. The benchmark is
deterministic and offline: it runs hook-policy cases, context helper smoke
checks, and runtime handoff budget checks without mutating protected fixtures
during normal runs. It emits `METRIC` lines for
`firehose_command_block_rate`, `bounded_command_allow_rate`,
`suggested_command_quality`, `needle_map_script_smoke_rate`, and
`compact_handoff_budget_rate`, then derives `compact_context` and
`bounded_tool_calls` for the RASS v1 scorecard. Any failed token-efficiency
metric fails the benchmark hard gate even if the aggregate acceptance score
would otherwise pass.

Memory Retrieval v2 adds `config/scorecards/memory_retrieval_v2.yaml` and `scripts/evals/memory_tree_benchmark.py`. The benchmark runs only against synthetic fixtures in an isolated temporary Ralph home, emits `METRIC name=value` lines, and hard-fails on RED indexing, raw leakage in hook-like output, wrong project/branch/worktree acceptance, or non-deterministic replay.

The Memory Retrieval v2 scorecard adds benchmark-specific hard gates for `red_not_indexed`, `no_raw_leak_in_hook_output`, `wrong_scope_rejected`, and `deterministic_replay`. Phase 14 final validation records the current benchmark JSON, scorecard result, and command outputs in `docs/reports/memory-tree-v2/14-final-validation.md`. Benchmark claims in user-facing docs should cite that report or a newer JSON output rather than relying on stale console history.

Memory quality checks now include the deterministic dream/consolidation flow. The expected behavior is that RED inputs are skipped without leaking raw content, repeated candidates are deduplicated, dry-run mode does not mutate L1-L3 or MiVault, and candidate layer targeting separates L1 essentials, L2 project rules, L3 vault index pointers, and report-only observations. The auto-use path must update only L4 dream state, and the MiVault path must write only reviewable inbox digests until candidates are explicitly promoted.

AutoResearch Global V2 extends the eval-only dry run into a reusable loop for target repos. Session state lives in `autoresearch.md`, `autoresearch.jsonl`, `autoresearch.ideas.md`, and `autoresearch.last-run.json`. Benchmarks emit `METRIC name=value`; `next.py` captures packet evidence, `log.py --from-last` records `keep`, `discard`, `crash`, or `checks_failed`, and stale-packet checks prevent logging evidence after unrelated changes. Every packet includes scorecard id/version, primary metric, direction, delta, hard gates, scoped commit paths, ASI, and timestamp.

New sessions default to `baseline_policy=best_kept`, with `initial` and
`latest_kept` retained as explicit compatibility policies. `log.py --status
keep` fails closed unless required hard gates are present and true:
`tests_pass`, `no_secret_leak`, `eval_harness_unchanged`,
`no_scope_violation`, `no_eval_gaming`, `fresh_packet`, and
`finite_primary_metric`.

Optional generation bundles live under
`autoresearch.runs/<segment_id>/gen_<n>/`. They store bounded stdout/stderr
previews, metrics, checks, hard gates, decisions, ASI, improvement notes, and
trace metadata after RED scanning. `PostToolUse` can also attach bounded
pending metric observations under the project runtime path
`~/.ralph-codex/projects/<project_id>/autoresearch/`; hooks do not run
benchmarks, Git scans, external advisors, MCP tools, or synthesis inline.

The deterministic fixture remains the acceptance gate for this behavior. It now covers kept candidates, low-delta discard, missing primary metrics, crash/checks_failed status handling, and fixture mutation protection.

Related phases: [PHASE_11](../migration/checkpoints/PHASE_11.md), [PHASE_12](../migration/checkpoints/PHASE_12.md), [PHASE_13](../migration/checkpoints/PHASE_13.md).
