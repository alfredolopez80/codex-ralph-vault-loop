# Runtime optimization v2 — final rollout evidence

Date: 2026-08-09
Branch: `codex/optimize-runtime-token-overhead-v2`
Candidate: `298496beae698c31f84101219ff52776fcb572ed`
Recorded baseline: `4784a55dd2b33e874ff8e615c6afe1488a8402dc`

## Executive verdict

The optimized runtime passes project-local structural, safety, continuity,
quality, and benchmark gates. The project-local canary is **PASS**. The global
rollout is **PENDING ONE EXPLICIT USER AUTHORIZATION**: the installer dry-run
is safe, but no global file was changed. No push, merge, or PR creation was
performed.

## Architecture before/after

| Lifecycle group  | Baseline configured | Candidate configured |            Delta | Candidate role                 |
| ---------------- | ------------------: | -------------------: | ---------------: | ------------------------------ |
| SessionStart     |                   1 |                    1 |                0 | `session_start_dispatch`       |
| UserPromptSubmit |                   5 |                    1 |      -4 (-80.0%) | `user_prompt_dispatch`         |
| PreToolUse       |                   3 |                    1 |      -2 (-66.7%) | `pre_tool_dispatch`            |
| PostToolUse      |                   6 |                    1 |      -5 (-83.3%) | `post_tool_dispatch`           |
| SubagentStart    |                   1 |                    1 |                0 | `sol_advisor_subagent_context` |
| SubagentStop     |                   1 |                    1 |                0 | `sol_advisor_subagent_stop`    |
| Stop             |                   8 |                    1 |      -7 (-87.5%) | `stop_dispatch`                |
| **Total**        |              **25** |                **7** | **-18 (-72.0%)** | one role per event             |

The candidate validates tool names internally; matchers are not the only
destructive-action barrier. SessionStart uses the explicit
`startup|resume|clear|compact` matcher. UserPromptSubmit and Stop have no
matcher, as required by the event contract.

## A/B metrics

The historical baseline benchmark predates schema version 2. The comparator
rejects a direct JSON comparison as `cambio no comparable` instead of
inventing missing fields. Phase 16 recorded the normalized local baseline
timings below; this phase reran the schema-v2 candidate with seven measured
iterations and retains that limitation explicitly.

| Event path             |     Baseline p50 / p95 ms |                           Candidate p50 / p95 ms | Local delta / verdict                                         |
| ---------------------- | ------------------------: | -----------------------------------------------: | ------------------------------------------------------------- |
| SessionStart startup   |             725.7 / 802.3 |                    53.6 / 56.0 (max profile row) | -92.6% / -93.0%; PASS, child count 0                          |
| UserPromptSubmit       |           2166.0 / 2289.5 | 274.3 / 294.2 (`repeated_prompt`, SOL/LUNA rows) | one role and bounded delta; legacy aggregate is not identical |
| PreToolUse             |             128.4 / 130.8 |                           51.9–114.2 by scenario | scenario-specific; safety semantics unchanged                 |
| PostToolUse            |             243.7 / 261.3 |                           51.9–243.6 by scenario | one dispatcher; reads remain report-only                      |
| Stop allow             | 1041.2 / 1103.5 aggregate |                   62.5 / 64.7 (max SOL/LUNA row) | material local reduction; PASS target                         |
| Stop objective failure |          legacy aggregate |                           62.8 / 64.0 (LUNA/SOL) | one factual continuation; no phrase loop                      |

The seven-iteration candidate report contains 30 profile/scenario rows,
`matched_handler_count=48`, `executed_handler_count=48`,
`child_process_count=6`, aggregate p50/p95 `3275.553 / 3382.218` ms,
`output_bytes=5595`, `estimated_context_units=1399`,
`persisted_bytes_delta=166130`, `cache_hits=3`, `continuation_count=3`, and
`block_count=7`. Deferred maintenance is separate:

| Maintenance case         | Enqueue p50 / p95 ms | Runner p50 / p95 ms | Runner children | Persistence B |
| ------------------------ | -------------------: | ------------------: | --------------: | ------------: |
| `stop_allow`             |      62.514 / 65.094 |   183.922 / 184.848 |               1 |         15722 |
| `stop_allow_with_memory` |      64.138 / 66.627 |   184.779 / 185.873 |               1 |         16047 |
| `stop_objective_failure` |      64.134 / 66.073 |   187.956 / 196.115 |               1 |         16505 |
| `session_start_backlog`  |      55.198 / 56.409 |   183.003 / 184.495 |               1 |         11451 |

Maintenance timing is never included in interactive p50/p95.

## Target verdicts

| Target                          | Verdict | Evidence                                                  |
| ------------------------------- | ------- | --------------------------------------------------------- |
| one handler per lifecycle event | PASS    | candidate config has 7 total, one per event               |
| LUNA prompt hard cap 1800 B     | PASS    | max observed repeated prompt 1110 B                       |
| SOL prompt hard cap 800 B       | PASS    | max observed repeated prompt 575 B                        |
| SessionStart child count 0      | PASS    | all startup/compact rows measured at 0                    |
| Stop allow p95 bound            | PASS    | max observed 64.694 ms, below `max(250 ms, 40% baseline)` |
| one ordinary Stop continuation  | PASS    | three objective-failure profiles, one each                |
| phrase-only Stop block          | PASS    | isolated doubtful wording is allowed                      |
| no active MCP duplicate         | PASS    | TOML audit and minimal gates                              |
| max_threads=2, max_depth=1      | PASS    | config and structural gate                                |
| AGENTS.md <=14 KiB              | PASS    | 14179 bytes                                               |

## Quality and security verdict

Quality is deterministic fixture quality, not free-form model answer quality:
the routing mock scored `0.9905`, continuity-flow validation passed, and the
full suite passed `992 tests` with five subtests. Coverage includes
destructive-command denial, path/symlink guards, package-manager SFW policy,
local-only RED routing, file-line hard gates, implementation notes, output
contracts, and Stop continuation caps. No critical or high findings remain
open from the adversarial review. The only global failures are the expected
installed-source mismatch, because installation was deliberately not
authorized.

## Estimated scaffold saving (local proxy only)

The structural proxy is 25 configured handlers before versus 7 after (72%
fewer configured process roles), with 80% fewer UserPromptSubmit roles, 83.3%
fewer PostToolUse roles, and 87.5% fewer Stop roles. The context proxy is
`ceil(output_bytes / 4)`: useful for relative fixture comparison, but not a
token or credit meter. No monetary, provider, cached-input, or account-credit
saving is asserted.

## Observability limits

Runtime records contain bounded IDs/hashes, counts, enumerated reasons, profile
and model family, tool family, byte counts, and monotonic durations. They do
not store task text, assistant response, raw tool body, raw vault content,
credentials, customer data, or a transcript. Child-process attribution is
reported only when a known child emits a bounded event; unknown is not silently
converted to zero. Telemetry overhead is included in measured wall time and is
local evidence only.

The top-level benchmark flag remains `subscription_usage_measured=false`. It
does not expose internal units, cached input, output billing, account limits,
or actual credits.

## Optional user-provided Usage export

If the user exports a Usage CSV/JSON manually, the privacy-safe reporter can
accept it without authentication or scraping:

```bash
python3 scripts/evals/report_runtime_overhead.py \
  --input /tmp/runtime-events.jsonl \
  --usage /tmp/user-supplied-usage.json \
  --json-out /tmp/runtime-report.json \
  --markdown-out /tmp/runtime-report.md
```

The import is labeled `user_supplied_usage`, rejects ambiguous timestamps, and
never turns that optional file into a verified subscription claim.

## Canary, rollback, and dry-run

The complete project-local procedure, abort matrix, rollback recipes, state
schema compatibility, dry-run output, target hashes, and pending approval are
in [18-canary-and-rollout.md](18-canary-and-rollout.md). The PR text prepared
but intentionally not opened is in [18-pr-draft.md](18-pr-draft.md).

## Commit list

- Phase 18 final documentation commit (this commit) — `docs: finalize optimized runtime rollout and rollback`
- `298496beae698c31f84101219ff52776fcb572ed` — `fix: address adversarial runtime optimization findings`
- `7543e206` — `test: gate runtime overhead and quality regressions`
- `f3ea66c33bd0a7ffd91d0400c9db7acd6724f5d1` — `feat: add privacy-safe scaffold cost attribution reports`
- `a783fb9`, `9568ba0`, `a33e81f`, `47afd1e`, `2058b20`, `ea12f8e`, `17708c9` — preceding optimization phases

## Validation ledger

| Check                                                         | Result                                                                                                            |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q` | `992 passed, 5 subtests passed`                                                                                   |
| hook shell suite                                              | `ALL_HOOK_TESTS_PASS`                                                                                             |
| project doctor                                                | `DOCTOR_PASS`                                                                                                     |
| minimal gates                                                 | `1 passed, 2 skipped, 0 failed`                                                                                   |
| coding-model mock                                             | score `0.9905`, status completed                                                                                  |
| Ralph memory flow                                             | `PASS`                                                                                                            |
| global smoke/doctor                                           | expected failure: installed stable checkout lacks candidate dispatcher sources; no install attempted              |
| `pre-commit run --all-files`                                  | YAML/compile/shellcheck/shfmt/secrets/semgrep passed; existing unrelated skill/doc formatting files fail Prettier |

## Final boundary

Project-local canary, rollback simulation, A/B evidence, and the global dry-run
are complete. The sole pending action is an explicit user decision to apply
the installer globally from the stable checkout. No global installation,
push, merge, or PR creation occurred.
