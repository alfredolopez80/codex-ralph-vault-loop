# Phase 12: Hook Integration Feature Flag

Status: PASS

## Scope

Integrated Memory Tree recall v2 into the task-intake hook flow behind `RALPH_MEMORY_RECALL_ENGINE=tree`. Legacy recall remains the default. Shadow mode remains measurement-only with `RALPH_MEMORY_TREE_SHADOW=1`.

## Files Changed

- `scripts/memory/task-intake.py`
- `tests/integration/test_memory_tree_hook_flow_e2e.py`
- `tests/golden/test_final_prompt_memory_block.py`
- `tests/golden/fixtures/final_prompt_memory_blocks/non_authoritative_markers.txt`
- `docs/architecture/memory-tree-v2.md`
- `docs/reports/memory-tree-v2/12-hook-integration-feature-flag.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

## Implementation Summary

- Added feature flag detection for `RALPH_MEMORY_RECALL_ENGINE=tree`.
- Preserved legacy as the default when the env var is unset.
- Preserved measurement-only shadow mode. If `RALPH_MEMORY_TREE_SHADOW=1`, legacy remains injected even when the tree engine env var is also set.
- Added tree recall prompt-context construction using the existing delimited non-authoritative memory block.
- Rendered only depth-0 safe tree fields into hook final prompts: node id, summary, trigger, topic tags, confidence, and safe flags.
- Excluded raw bodies, raw refs, and detailed summaries from hook prompt injection.
- Added fail-open fallback to legacy when tree recall raises.
- Added trace fields for `engine`, `fallback_used`, `raw_included`, `raw_recommended`, `reached_final_prompt`, and token budget used/limit.
- Kept `CLARIFICATION_REQUIRED`, task classification, route decision behavior, PostToolUse stdout, and Stop stdout behavior unchanged.

## Tests Added

- `tests/integration/test_memory_tree_hook_flow_e2e.py`
- `tests/golden/test_final_prompt_memory_block.py`
- `tests/golden/fixtures/final_prompt_memory_blocks/non_authoritative_markers.txt`

Coverage includes:

- default env uses legacy
- tree env injects v2 memory
- final prompt contains non-authoritative delimited block
- tree fallback uses legacy and does not expose exception details
- shadow remains measurement-only
- raw content never appears in hook payload or final prompt
- irrelevant memory is not injected
- stale memory is not injected

## Commands Run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/golden/test_final_prompt_memory_block.py tests/integration/test_memory_tree_hook_flow_e2e.py -q
```

Result: PASS, `6 passed in 0.21s`.

```bash
RALPH_MEMORY_RECALL_ENGINE=tree PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_memory_tree_hook_flow_e2e.py tests/unit/test_memory_recall_v2.py -q
```

Result: PASS, `15 passed in 1.37s`.

```bash
RALPH_MEMORY_TREE_SHADOW=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_shadow_mode.py tests/integration/test_memory_recall_flow_e2e.py -q
```

Result: PASS, `8 passed in 0.18s`.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_hook_config_lockstep.py tests/integration/test_hooks_basic.py tests/integration/test_global_install_basic.py -q
```

Result: PASS, `75 passed in 44.14s`.

```bash
bash .codex/tests/run-hook-tests.sh
```

Result: PASS, `ALL_HOOK_TESTS_PASS`.

```bash
bash scripts/validate-ralph-memory-flow.sh
```

Result: PASS. Memory unit tests, fake recall integration, post-hook write safety tests, and shell lint passed; `ruff` and `mypy` remained optional skips because they are not installed.

```bash
python3 scripts/evals/memory_tree_benchmark.py --fixture tests/evals/fixtures/memory_tree_retrieval --output /tmp/ralph-memory-tree-benchmark.json
```

Result: PASS.

Key metrics:

- `memory_tree_score=0.9895`
- `summary_precision_at_3=1.0000`
- `trigger_recall_at_3=1.0000`
- `exact_fact_accuracy=1.0000`
- `raw_needed_detection=1.0000`
- `raw_open_minimized=1.0000`
- `wrong_scope_rejected=1.0000`
- `stale_rejected=1.0000`
- `red_not_indexed=1.0000`
- `no_raw_leak_in_hook_output=1.0000`
- `graph_hop_recall=1.0000`
- `token_budget_observed=1.0000`
- `provenance_complete=1.0000`
- `deterministic_replay=1.0000`

```bash
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark.json
```

Result: PASS. Score `0.9993`; hard gates passed with no failures.

```bash
python3 scripts/gates/run-gates.py --minimal
```

Result: PASS. Summary: `failed=0`, `passed=1`, `skipped=2`, `status=passed`.

Optional global hook checks:

```bash
python3 scripts/setup/smoke-global-hooks.py
bash scripts/setup/doctor-global.sh
```

Result: PASS. `GLOBAL_HOOKS_SMOKE_PASS` and `GLOBAL_DOCTOR_PASS warnings=0`.

## Known Limitations

- Tree hook integration is still opt-in through `RALPH_MEMORY_RECALL_ENGINE=tree`.
- Tree recall injection uses only safe depth-0 fields. Exact raw inspection remains an explicit CLI action.
- Tree recall fallback reports the exception type only, not exception details.
