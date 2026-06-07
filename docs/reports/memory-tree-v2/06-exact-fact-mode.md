# Ralph Cognitive Memory Tree v2 - 06 Exact Fact Mode

Date: 2026-06-07

Repository: `alfredolopez80/codex-ralph-vault-loop`

Active worktree: `/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop`

Phase result: PASS

## Scope

Phase 06 adds exact-fact risk detection to `recall_v2.py`.

No hooks were modified. Legacy recall was not modified. Exact-fact mode can recommend raw inspection, but recall still does not include raw content automatically.

## Files Changed

Added:

- `tests/unit/test_memory_exact_fact_mode.py`
- `docs/reports/memory-tree-v2/06-exact-fact-mode.md`

Updated:

- `scripts/memory/recall_v2.py`
- `docs/architecture/memory-tree-v2.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

## Implementation Summary

Exact-fact detection now recognizes deterministic query cues for:

- exact command
- exact file path
- exact function name
- exact class name
- exact benchmark metric
- exact date
- exact version
- exact number
- quote or reproduce prior wording
- specific config/key existence
- exact `selected_memory_ids` from a prior trace

When exact-fact mode is detected:

- `risk_level=high`
- `raw_recommended=true`
- `raw_included=false`
- selected nodes include a suggested explicit reader command:

```bash
python3 scripts/memory/read_memory_node.py --project-root . --node-id <id> --depth 2 --redact
```

Recall still enforces the existing budget and hard filters. High-risk recall output remains summary/trigger only; it does not include detailed summaries or raw bodies.

Scoring was tightened so recency and salience cannot select a node by themselves. A node must first match summary, trigger, entity, tag, or path content.

## Tests Added

`tests/unit/test_memory_exact_fact_mode.py` covers:

- exact command query marks high risk
- exact path query marks high risk
- exact function query marks high risk
- exact class query marks high risk
- exact benchmark metric query marks high risk
- exact date query marks high risk
- exact version query marks high risk
- exact number query marks high risk
- quote query marks high risk
- config/key query marks high risk
- selected memory ids query marks high risk
- conceptual query remains low or medium risk
- raw is never included
- suggested read command appears only when a node is selected
- trace includes risk level and raw recommendation state
- budget remains enforced

## Commands Run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_exact_fact_mode.py -q
```

Initial result:

```text
2 failed, 7 passed in 1.04s
```

Fixes made:

- `exact benchmark metric` now sets exact-fact mode when `exact` appears with another exact-risk term.
- Scoring now requires an actual text-field match before recency and salience can boost a node.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_exact_fact_mode.py tests/unit/test_memory_recall_v2.py -q
```

Result:

```text
19 passed in 1.96s
```

```bash
bash scripts/validate-ralph-memory-flow.sh
```

Result:

```text
25 passed in 0.03s
2 passed in 0.02s
6 passed, 48 deselected in 0.49s
PASS shell lint: validate-ralph-memory-flow.sh
SKIP python lint: Ralph memory flow files (ruff not installed)
SKIP python typecheck: Ralph memory flow files (mypy not installed)
Ralph memory flow validation summary: PASS
```

```bash
python3 scripts/gates/run-gates.py --minimal
```

Result:

```json
{
  "json": ".ralph-codex/reports/gates/latest.json",
  "markdown": ".ralph-codex/reports/gates/latest.md",
  "summary": {
    "failed": 0,
    "passed": 1,
    "skipped": 2,
    "status": "passed"
  }
}
```

## Acceptance Criteria

- Exact fact detection works: PASS.
- Raw remains opt-in: PASS.
- Legacy behavior unchanged: PASS.
