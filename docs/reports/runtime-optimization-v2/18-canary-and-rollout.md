# Runtime optimization v2 — project-local canary and rollout plan

Date: 2026-08-09

This report records a project-local canary and the guarded rollout boundary.

Candidate: `298496beae698c31f84101219ff52776fcb572ed`

The measurements are local process and context proxies. They do not observe
provider accounting or account limits. The report flag remains `false`.

Branch: `codex/optimize-runtime-token-overhead-v2`
Recorded baseline: `4784a55dd2b33e874ff8e615c6afe1488a8402dc`

Each case sets `RALPH_HOME`, `CODEX_HOOK_STATE_ROOT`, and `VAULT_DIR` below a
fresh temporary directory.

## Canary manifest

The benchmark ran 10 deterministic scenarios, three profiles, one warmup, and
five measured iterations per profile/scenario: 150 measured samples plus four
deferred-maintenance fixtures. This exceeds the 20-event minimum. LUNA covers
all ten scenarios; SOL covers all ten (including the required three SOL
cases); `conservative_unknown` is the third safety profile.

| Scenario                 | Event(s)            | Deterministic fixture                    | Assertion                                          |
| ------------------------ | ------------------- | ---------------------------------------- | -------------------------------------------------- |
| `small_read_only`        | Pre/PostToolUse     | `exec_command` with `git status --short` | read-only call, empty stdout                       |
| `small_edit`             | Pre/PostToolUse     | bounded `apply_patch` of `notes.md`      | file-line and shaping guards active                |
| `medium_edit_test`       | Pre/PostToolUse     | source edit followed by a passing test   | mutation, test and checkpoint attribution          |
| `repeated_prompt`        | UserPromptSubmit x2 | fixed task signature and generation      | second claim is a cache hit and emits only a delta |
| `session_start_startup`  | SessionStart        | `source=startup` and one sentinel id     | bounded wakeup, no child process                   |
| `session_start_compact`  | SessionStart        | `source=compact` and scoped checkpoint   | compact continuity package only                    |
| `stop_allow`             | Stop                | `verified_done=true`                     | empty stdout and zero continuation                 |
| `stop_objective_failure` | Stop                | current scoped failure fingerprint       | one factual continuation                           |
| `subagent_route`         | PreToolUse          | one bounded `spawn_agent` packet         | budget/routing decision                            |
| `red_safety`             | PreToolUse          | synthetic policy-only RED classification | local deny; no body persisted                      |

## Reproduction procedure

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q

python3 scripts/evals/hook_runtime_cost_benchmark.py \
  --iterations 5 --warmup 1 \
  --json-out /tmp/phase18-canary.json \
  --markdown-out /tmp/phase18-canary.md

python3 scripts/evals/hook_runtime_cost_benchmark.py \
  --iterations 7 --warmup 1 \
  --json-out /tmp/phase18-ab-candidate.json \
  --markdown-out /tmp/phase18-ab-candidate.md

python3 scripts/evals/compare_hook_benchmarks.py \
  --baseline /tmp/phase17-final-benchmark.json \
  --candidate /tmp/phase18-ab-candidate.json \
  --noise-threshold 0.10
```

The phase artifacts are `/private/tmp/phase18-canary.json` and
`/private/tmp/phase18-ab-candidate.json`; they are temporary evidence, not
repository state.

## Canary measurements

The five-iteration canary aggregate was:

| Measure                                |                                Result |
| -------------------------------------- | ------------------------------------: |
| schema version                         |                                     2 |
| measured samples                       |                                   150 |
| configured handlers by event           |     1 each for all 7 lifecycle events |
| matched/executed handler counts        |    48 / 48 across the scenario matrix |
| measured child processes               | 6 (known repeated-prompt recall path) |
| aggregate p50/p95 (matrix sum)         |                3128.379 / 3218.334 ms |
| output bytes / estimated context units |                           5595 / 1399 |
| persistence delta                      |                              166128 B |
| blocks / continuations                 |                                 7 / 3 |
| cache hits                             |                                     3 |
| advisors                               |                                     0 |
| subscription usage measured            |                               `false` |

The aggregate sums independent cases; it is not a model-latency or account
cost estimate. Key rows were:

| Scenario/profile              |      p50 / p95 ms | matched / executed | output B / context units | blocks / continuations | child processes |
| ----------------------------- | ----------------: | -----------------: | -----------------------: | ---------------------: | --------------: |
| `small_read_only` LUNA        | 105.761 / 111.123 |              2 / 2 |                    0 / 0 |                  0 / 0 |               0 |
| `small_read_only` SOL         | 114.236 / 115.707 |              2 / 2 |                    0 / 0 |                  0 / 0 |               0 |
| `medium_edit_test` LUNA       | 227.136 / 232.341 |              4 / 4 |                    0 / 0 |                  0 / 0 |               0 |
| `repeated_prompt` LUNA        | 264.749 / 272.340 |              2 / 2 |               1110 / 278 |                  0 / 0 |               2 |
| `repeated_prompt` SOL         | 273.096 / 280.687 |              2 / 2 |                575 / 144 |                  0 / 0 |               2 |
| `session_start_startup` LUNA  |   51.421 / 52.351 |              1 / 1 |                 329 / 83 |                  0 / 0 |               0 |
| `session_start_compact` SOL   |   50.855 / 52.096 |              1 / 1 |                 267 / 67 |                  0 / 0 |               0 |
| `stop_allow` LUNA             |   58.132 / 60.223 |              1 / 1 |                    0 / 0 |                  0 / 0 |               0 |
| `stop_objective_failure` LUNA |   59.663 / 59.938 |              1 / 1 |                 173 / 44 |                  1 / 1 |               0 |
| `red_safety` LUNA             |   51.944 / 53.288 |              1 / 1 |                 114 / 29 |                  1 / 0 |               0 |

The seven-iteration repeat produced aggregate p50/p95 `3275.553 / 3382.218`
ms, with the same structural counts, `cache_hits=3`, `continuation_count=3`,
and `subscription_usage_measured=false`. The schema comparator found no
semantic changes against the preceding candidate; at a 10% noise threshold it
returned `mejora`, with most rows classified as `ruido`.

## Abort criteria and observed result

| Abort condition                | Evidence                                                                             | Result                       |
| ------------------------------ | ------------------------------------------------------------------------------------ | ---------------------------- |
| privacy boundary breach        | denylist tests, gitleaks and semgrep passed; no raw body in runtime schema           | PASS                         |
| destructive action not blocked | hook safety matrix and full hook tests                                               | PASS                         |
| relevant recall lost           | selection, injection, fallback and scope tests with sentinel fixtures                | PASS                         |
| Stop loop                      | objective failure has one continuation per task; phrase-only test allows             | PASS                         |
| hard gate omitted              | runtime structural gate and objective gate tests                                     | PASS                         |
| state corruption               | cache/queue corrupt-state and quarantine tests                                       | PASS                         |
| quality regression             | deterministic routing/profile/memory scorecards; mock score 0.9905                   | PASS                         |
| unexplained p95 regression     | legacy baseline limitation documented; repeat candidate within noise                 | PASS with limitation         |
| output cap broken              | LUNA prompt max 1110 B (<1800), SOL max 575 B (<800), SessionStart max 345 B (<2200) | PASS                         |
| global/project duplicate       | candidate has one role per event; global state remains old and inactive              | PROJECT PASS; GLOBAL PENDING |

The canary verdict is **PASS for project-local activation** and **NOT YET
ACTIVATED globally**. A global result cannot be claimed before explicit user
authorization.

## Rollback levels

### 1. Conservative profile/configuration

The runtime can be made conservative without changing files:

```bash
export RALPH_SCAFFOLD_PROFILE=conservative
```

This preserves all safety gates and only reduces optional scaffold budgets.
Return to automatic classification with `unset RALPH_SCAFFOLD_PROFILE`.
Retention is independently bounded with `RALPH_CONTEXT_CACHE_TTL_SECONDS`,
`RALPH_CONTEXT_CACHE_MAX_ENTRIES`, `RALPH_MAINTENANCE_TTL_SECONDS`, and
`RALPH_MAINTENANCE_MAX_ENTRIES`; lowering those values is diagnostic and does
not remove existing records.

### 2. Revert the optimization commits

This is a recipe only; it was not executed in the canary:

```bash
git revert --no-edit \
  298496beae698c31f84101219ff52776fcb572ed \
  7543e206 \
  f3ea66c33bd0a7ffd91d0400c9db7acd6724f5d1 \
  a783fb9 \
  9568ba0 \
  a33e81f \
  47afd1e \
  2058b20 \
  ea12f8e \
  17708c9
```

The recorded baseline remains
`4784a55dd2b33e874ff8e615c6afe1488a8402dc`. Preserve the branch and evidence;
do not use `reset --hard` for rollback.

### 3. Restore an authorized global install from backup

The installer creates, but never automatically deletes, these backups:

```text
~/.codex/hooks.bak-global-hooks/
~/.codex/hooks.json.bak-global-hooks
```

If a global install is later authorized and must be rolled back, preserve the
current state first, copy the backups back, then run both diagnostics:

```bash
stamp=$(date +%Y%m%d-%H%M%S)
mv ~/.codex/hooks ~/.codex/hooks.before-rollback."$stamp"
cp -a ~/.codex/hooks.bak-global-hooks ~/.codex/hooks
cp ~/.codex/hooks.json.bak-global-hooks ~/.codex/hooks.json
bash scripts/setup/doctor-global.sh
python3 scripts/setup/smoke-global-hooks.py
```

The backup paths are not removed by this procedure. They were inspected
read-only in this phase; no restore was performed.

### State/schema compatibility

The task-context cache, SessionStart state, post-tool dedupe state, and
maintenance queue are each versioned (`schema_version=1`), private, bounded,
atomic, and fail-open. An older checkout does not depend on these files and
can ignore them; the current checkout quarantines corrupt or incompatible JSON
and recovers with empty state. The queue stores descriptors only, so rollback
never requires copying task text, memory body, tool output, or vault content.

The explicit rollback simulation covered corruption, TTL, bounded eviction,
symlink refusal, permissions, and concurrent writers:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
  tests/unit/test_maintenance_queue.py \
  tests/unit/test_context_delta.py \
  tests/unit/test_runtime_state_hardening.py \
  tests/unit/test_runtime_optimization_gate.py -q
```

Result: `32 passed in 0.28s`.

## Global installer dry-run (no mutation)

Commands used:

```bash
python3 scripts/setup/install-global-hooks.py --dry-run
HOME=/private/tmp/phase18-dry-home \
  python3 scripts/setup/install-global-hooks.py --dry-run
```

The first real dry-run was intentionally refused:

```text
GLOBAL_HOOKS_REFUSED_SOURCE_MISMATCH
marker=/Users/alfredolopez/.codex/hooks/.ralph-repo-root
hint=run the full global installer migration
```

This protects the current global installation, which points to the stable
checkout while this branch lives in a temporary comparison checkout. An
isolated dry-run with `HOME=/private/tmp/phase18-dry-home` rendered the plan
without reading or writing the real global state:

| Item                  | Planned value                                                                                                                                                                |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----- | --------------- | ------------ | ----------- | ---- | ----- | ----- | ----------- | -------------------------------------------------------------------------------- |
| target hook directory | `~/.codex/hooks/`                                                                                                                                                            |
| target config         | `~/.codex/hooks.json`                                                                                                                                                        |
| source marker         | `~/.codex/hooks/.ralph-repo-root`                                                                                                                                            |
| backup directory      | `~/.codex/hooks.bak-global-hooks/`                                                                                                                                           |
| backup config         | `~/.codex/hooks.json.bak-global-hooks`                                                                                                                                       |
| configured roles      | 7: `session_start_dispatch`, `user_prompt_dispatch`, `pre_tool_dispatch`, `post_tool_dispatch`, `sol_advisor_subagent_context`, `sol_advisor_subagent_stop`, `stop_dispatch` |
| matchers              | `startup                                                                                                                                                                     | resume | clear | compact`; `Bash | exec_command | apply_patch | Edit | Write | Agent | spawn_agent | mcp\_\_._`; `._` for PostToolUse; none for UserPromptSubmit/Stop/Subagent events |
| context limits        | SessionStart 800; UserPromptSubmit 500; SubagentStart 400; none on Stop                                                                                                      |
| command shape         | `python3 ~/.codex/hooks/global_hook_dispatch.py --event <event> --role <role>`                                                                                               |

The read-only hashes before any possible authorization were:

```text
hooks.json                 9e563ae90f757dfb44361d0a2f2e540494388413a8293586137dafc69b30f283
.ralph-repo-root           db1a0580968dd63fd3b791aee3c7dfe316a29dea51206aa1c04cbe5b7522638e
hooks directory manifest   92c7eb3e464409c5557dd661ba3d43213b40f631a27aa120cac46772c8703b6a
hooks.json backup          9e563ae90f757dfb44361d0a2f2e540494388413a8293586137dafc69b30f283
hooks backup manifest      db2e646a5b29d190e8a21bcb69b7765e03923e12346a86e58b0be33b9e1baa6b
```

The current global configuration still exposes the legacy 25-handler shape:
SessionStart 1, UserPromptSubmit 5, PreToolUse 3, PostToolUse 6,
SubagentStart 1, SubagentStop 1, Stop 8. The candidate project config has
one handler per event and the MCP audit reports no active duplicate endpoint or
schema. No global duplicate was silently overwritten.

The only remaining rollout decision is whether the user explicitly authorizes
applying this dry-run from the stable checkout. Until then, no global file,
backup, symlink, or trust setting is changed.

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

## Pending approval

Project-local canary and rollback simulation are complete. The next action is
not automatic: explicitly authorize or decline applying the global installer
from the stable checkout. No push, merge, PR creation, or global installation
has occurred.
