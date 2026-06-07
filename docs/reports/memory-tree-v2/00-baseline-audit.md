# Ralph Cognitive Memory Tree v2 - 00 Baseline Audit

Date: 2026-06-07

Repository: `alfredolopez80/codex-ralph-vault-loop`

Active worktree: `/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop`

Commit audited: `8cce4aa700cb836382008f8374f891741fb13a72`

Phase result: PASS

Branch status: PASS_WITH_BLOCKER. The worktree was clean, but dedicated branch creation was blocked because Git refs are stored under the primary checkout common git dir outside the writable worktree.

## Scope

This phase establishes the current baseline before Ralph Cognitive Memory Tree v2. It does not design, implement, or change runtime behavior.

No package installation was performed. No hooks, gates, pre-commit, semgrep, gitleaks, or security checks were bypassed. No RED content was persisted, printed, or routed externally. Memory was treated as non-authoritative context.

## Initial Commands

`git status --short`

Result: pass, no output.

`git branch --show-current`

Result: pass, no output. The active worktree had no branch name.

`git checkout -b feature/ralph-memory-tree-v2`

Result: fail, branch creation blocker.

```text
fatal: cannot lock ref 'refs/heads/feature/ralph-memory-tree-v2': unable to create directory for /Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop/.git/refs/heads/feature/ralph-memory-tree-v2
```

Follow-up identity checks:

- `git rev-parse HEAD`: `8cce4aa700cb836382008f8374f891741fb13a72`
- `git remote get-url origin`: `https://github.com/alfredolopez80/codex-ralph-vault-loop.git`
- `git rev-parse --show-toplevel`: `/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop`
- `git rev-parse --git-common-dir`: `/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop/.git`

## Inspected Surfaces

- `AGENTS.md`
- `README.md`
- `SECURITY.md`
- `docs/architecture/memory-stack.md`
- `docs/architecture/evaluation-spine.md`
- `docs/architecture/threat-model.md`
- `.codex/hooks.json`
- `.codex/hooks/`
- `scripts/memory/`
- `scripts/evals/`
- `scripts/gates/`
- `scripts/setup/`
- `config/scorecards/`
- `tests/unit/`
- `tests/integration/`

## Current Memory Lifecycle

### SessionStart

Configured by `.codex/hooks.json` to run `.codex/hooks/session_start_wakeup.py`.

Current behavior:

- Resolves active project context from hook payload using `.codex/hooks/shared/active_context.py`.
- Ensures the Ralph runtime root exists.
- Runs `scripts/memory/dream-scheduler.py --catch-up --target-time 11:30` when present.
- Runs `scripts/memory/wakeup.py --project <slug> --project-id <id> --workspace-root <root>`.
- `wakeup.py` builds compact context from L0/L1 global layers and project-scoped L2-L4 layers, latest eligible handoff, and latest eligible rolling checkpoint.

SessionStart rejection gates:

- Handoff body must not be RED.
- Handoff classification must be GREEN or YELLOW for project-scoped injection.
- Handoff project id must match.
- Handoff session id must match when available.
- Handoff workspace instance id must match.
- Handoff timestamp must be fresh.
- Same handoff hash is not reinjected for the same session.
- Checkpoint must pass `checkpoint_is_injectable`.

### UserPromptSubmit

Configured by `.codex/hooks.json` to run:

- `.codex/hooks/universal-prompt-classifier.sh`
- `.codex/hooks/aristotle-analysis-display.sh`
- `.codex/hooks/user_prompt_capture.py`
- `.codex/hooks/continuity_prompt_context.py`

Current behavior:

- `user_prompt_capture.py` rejects context-budget violations before prompt capture.
- Non-RED prompts are persisted only as safe prompt metadata: hash, terms, project id, session id, and workspace root.
- `user_prompt_capture.py` calls `scripts/memory/task-intake.py` with project, project id, workspace root, and branch.
- `task-intake.py` classifies sensitivity, task type, complexity, route, and optional clarification state.
- If the prompt is not vague and recall is enabled, `task-intake.py` calls `scripts/memory/ralph-recall.py` before constructing `agent_prompt_context`.
- `continuity_prompt_context.py` updates the rolling checkpoint for new task-like prompts, and injects the latest rolling checkpoint only for continuation prompts such as `continua`, `continue`, or exact `resume`.

### PreToolUse

Configured by `.codex/hooks.json` to run `.codex/hooks/pre_tool_guard.py`.

Current behavior includes blocking destructive commands, sensitive file reads, stale repo-local wakeup commands, direct cron automation, and unprotected package-manager network commands.

### PostToolUse

Configured by `.codex/hooks.json` to run:

- `.codex/hooks/file_line_guard.py --event PostToolUse`
- `.codex/hooks/shaping_ripple.py`
- `.codex/hooks/post_tool_extract_memory.py`
- `.codex/hooks/post_tool_checkpoint.py`
- `.codex/hooks/post_tool_cost_ledger.py`

Current behavior:

- `post_tool_extract_memory.py` extracts learning-like text from bounded tool output fields and calls `save_learning(..., classification="YELLOW")`.
- `save_learning` rejects empty, explicit RED, or classifier-RED text.
- `post_tool_checkpoint.py` updates the rolling checkpoint from safe summarized tool metadata and avoids raw output persistence.
- Cost/tool ledgers record metadata under project runtime paths.

### Stop

Configured by `.codex/hooks.json` to run:

- `.codex/hooks/anti-rationalization-stop.sh`
- `.codex/hooks/ralph-stop-quality-gate.sh`
- `.codex/hooks/file_line_guard.py --event Stop`
- `scripts/gates/codex_stop_slop_guard.py`
- `.codex/hooks/stop_route_decision_warn.py`
- `.codex/hooks/implementation_notes_guard.py`
- `.codex/hooks/stop_persist_memory.py`
- `.codex/hooks/stop_memory_promotion_review.py`

Current behavior:

- Stop quality and slop guards run before memory persistence.
- `implementation_notes_guard.py` enforces approved-plan notes when required.
- `stop_persist_memory.py` skips RED final assistant messages, creates a handoff from a safe final message plus eligible rolling checkpoint, and saves validated learning only when the payload does not indicate failure.
- `stop_memory_promotion_review.py` runs `scripts/memory/dream.py` report/promotion flows and writes memory review reports under the project runtime.

## Current Recall Path

Primary explicit recall path:

```text
UserPromptSubmit
  -> .codex/hooks/user_prompt_capture.py
  -> scripts/memory/task-intake.py
  -> scripts/memory/ralph-recall.py
  -> task-intake selection/rejection
  -> agent_prompt_context.final_prompt
```

`ralph-recall.py` searches:

- Repo `AGENTS.md` and repo-local skill `SKILL.md` files.
- Active project runtime `layers`, `handoffs`, and `ledgers` under `~/.ralph-codex/projects/<project_id>/`.
- Curated MiVault global and project `wiki`, `decisions`, `sessions`, and `handoffs`.

Default exclusions:

- MiVault inbox/raw.
- Sensitive-looking paths.
- Files classified RED by the sensitive-content classifier.

`--include-raw` opt-in adds global/project `raw` and `inbox` areas, but recall output still passes safety filtering.

## Where Memory Is Selected

Selection currently happens in `scripts/memory/task-intake.py`:

- `run_recall` executes `ralph-recall.py`.
- `parse_recall_results` parses JSON-like or markdown recall results.
- `select_relevant_memories_with_rejections` ranks candidates by score and time.
- `RECALL_CONTEXT_MIN_SCORE` is `20`.
- `RECALL_CONTEXT_LIMIT` is `3`.
- `RECALL_CONTEXT_MAX_TOKENS` is `180`.
- Selected memory is rendered as JSON lines between memory delimiters.

## Where Memory Is Rejected

Recall candidate rejection currently happens in `scripts/memory/task-intake.py`:

- `deprecated` or `is_deprecated`: rejected as `deprecated`.
- `stale` or `is_stale`: rejected as `stale`.
- Missing repo/project scope when project scope is required: `missing_scope_repo`.
- Repo/project mismatch: `wrong_repo`.
- Project id mismatch: `wrong_project_id`.
- Missing branch when branch scope is required: `missing_scope_branch`.
- Branch mismatch: `stale_branch`.
- Task type mismatch: `wrong_task_type`.
- Score below threshold: `below_min_score`.
- Empty content: `empty_memory`.
- Duplicate id/content: `duplicate_memory`.
- Over item budget: `max_memory_items`.
- Over token budget: `max_memory_tokens`.

Recall source rejection happens in `scripts/memory/ralph-recall.py`:

- Sensitive paths are skipped.
- RED-classified file contents are skipped.
- Inbox/raw is excluded unless `--include-raw`.

Checkpoint/handoff rejection happens in `scripts/memory/wakeup.py`, `.codex/hooks/continuity_prompt_context.py`, and `.codex/hooks/shared/checkpoint_io.py`:

- RED classification/content.
- Wrong project id.
- Wrong session id.
- Wrong workspace instance id.
- Wrong branch for checkpoints.
- Stale TTL.
- Already injected hash.
- Missing objective or next action for checkpoints.

## Where Memory Is Injected Into Final Prompt/Context

Recall injection:

- `scripts/memory/task-intake.py` builds `agent_prompt_context`.
- `build_agent_prompt_context` renders `selected_memory_context`.
- When memory exists, `final_prompt` contains delimited non-authoritative memory context followed by `User task:` and the original prompt.

Coverage boundary:

- Current tests prove this final prompt reaches a fake downstream agent in `tests/integration/test_memory_recall_flow_e2e.py`.
- The production hook emits the task-intake payload/context; this phase did not verify a real Codex internal final prompt handoff beyond the existing hook output path.

Continuation injection:

- `.codex/hooks/continuity_prompt_context.py` emits Codex hook JSON with `hookSpecificOutput.additionalContext` containing `Latest rolling checkpoint:` for continuation prompts only.
- `scripts/memory/wakeup.py` prints compact wakeup context on `SessionStart`.

## Where Memory Is Persisted

Project runtime root:

```text
~/.ralph-codex/projects/<project_id>/
```

Current persistence surfaces:

- `ledgers/user-prompts.jsonl`: hashed prompt metadata only, from `user_prompt_capture.py`.
- `ledgers/learning-<hash>.md`: validated learning only, from `save_learning`.
- `ledgers/learning-events.jsonl`: learning metadata.
- `checkpoints/latest.json`, `latest.md`, `archive/`, `events.jsonl`, `injection-state.json`: rolling checkpoint state.
- `handoffs/latest.md` and timestamped handoff archives: safe Stop handoff.
- `reports/memory/`: dream/promotion reports.
- `cost/tool-ledger.jsonl`: cost/tool metadata.
- `layers/L4_dream_state.md` and `.json`: optional dream state from scheduler/dream flows.

MiVault persistence:

- `scripts/memory/dream.py --vault-inbox` can write reviewable inbox digests.
- Graduation is handled separately by vault review/graduation scripts.

RED persistence controls:

- `save_learning` rejects RED.
- `write_handoff` rejects RED.
- Checkpoint update rejects RED.
- Dream/consolidation skips RED without raw content.

## Current RED/YELLOW/GREEN Rules

From `AGENTS.md`, `README.md`, `docs/architecture/memory-stack.md`, `docs/architecture/threat-model.md`, and code:

- GREEN: public or non-sensitive project context; eligible for durable memory and external MCP use when routing permits.
- YELLOW: internal or proprietary context that has been sanitized; eligible for project-specific durable memory and external MCP use only with minimized sanitized context.
- RED: user-marked sensitive content, secret-bearing material, credential-like data, customer-sensitive data, regulated data, or unsanitized sensitive logs.
- RED stays local, must not be routed externally, must not be stored in repo checkpoints, vault notes, handoffs, reports, or external MCPs, and is skipped by memory persistence.
- Retrieved memory is non-authoritative context; explicit user instructions and current repo files win.

## Current Validation Commands

Baseline validation commands required by this phase:

```bash
bash scripts/setup/doctor.sh
python3 scripts/gates/run-gates.py --minimal
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
python3 scripts/evals/coding_model_eval.py --mode mock
bash scripts/validate-ralph-memory-flow.sh
```

Additional validation commands documented by `AGENTS.md` for memory/hook changes:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_ralph_recall_context.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_memory_recall_flow_e2e.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_hooks_basic.py -q
bash .codex/tests/run-hook-tests.sh
python3 scripts/setup/smoke-global-hooks.py
bash scripts/setup/doctor-global.sh
```

`scripts/gates/run-gates.py --minimal` runs `scripts/gates/run-tests.py --mode minimal` and `scripts/gates/run-security.py --mode minimal`. Minimal security mode is skipped by design.

## Current Scorecards

Scorecards in `config/scorecards/`:

- `memory_retrieval_v1`: directly relevant to wakeup, retrieval, handoff behavior, RED safety, and vault linkage.
- `ralph_autoresearch_v1`: scores autonomous research loops.
- `cost_router_v1`: scores intent-aware MCP routing, Codex ownership, and safety-preserving delegation.
- `research_skill_v1`: scores sourced research behavior.

Shared hard gates across current scorecards:

- `tests_pass`
- `no_secret_leak`
- `eval_harness_unchanged`
- `no_scope_violation`
- `no_eval_gaming`

## Gap Baseline For Memory Tree v2

| Gap                       | Baseline status | Evidence                                                                                                                                                                               |
| ------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Summary index             | Partial/missing | L2/L3/L4 layers and dream summaries exist, but there is no dedicated memory-tree summary index optimized for progressive retrieval.                                                    |
| Trigger index             | Missing         | Recall query is lexical/task-derived in `task-intake.py`; no explicit trigger index was found.                                                                                         |
| Raw pointer               | Partial         | Raw/inbox can be included with `--include-raw`, but there is no structured raw pointer object that separates summary metadata from raw-open authorization.                             |
| Progressive retrieval     | Partial         | Wakeup compacts L0-L4/handoff/checkpoint; recall selects up to 3 items under token budget. No multi-stage summary to trigger to raw progressive tree path exists.                      |
| Graph links               | Partial/missing | Diagrams and vault graduation concepts exist, but recall candidates do not expose explicit graph edges between facts, sessions, branches, raw pointers, and derived summaries.         |
| Stale rejection           | Present         | `task-intake.py` rejects `stale`; checkpoints and handoffs enforce TTL.                                                                                                                |
| Wrong project rejection   | Present         | `task-intake.py` rejects `wrong_repo`/`wrong_project_id`; checkpoint/handoff injection requires matching project id.                                                                   |
| Wrong branch rejection    | Present/partial | `task-intake.py` rejects `stale_branch`; checkpoints compare branch when both checkpoint and active context have branch. Detached/empty branch compatibility remains a baseline edge.  |
| Exact fact recall         | Partial         | Lexical scoring and sentinel tests exist, but no dedicated exact-fact benchmark/index was found.                                                                                       |
| Raw-open minimization     | Partial         | Raw/inbox is excluded by default and requires `--include-raw`, but no separate audited raw-open minimization ledger was found for recall decisions.                                    |
| Final-prompt golden tests | Partial         | Unit and fake integration tests assert memory in `final_prompt`; no golden fixture suite for real Codex final prompt/context contract was found.                                       |
| Shadow mode               | Missing         | No explicit shadow-mode path was found for comparing v1 recall against v2 candidates without injection.                                                                                |
| Observability ledger      | Partial         | `MEMORY_TRACE_JSON`, learning events, checkpoint events, and cost ledgers exist, but no unified memory-tree observability ledger for selection/rejection/raw-open decisions was found. |

## Validation Results

### `bash scripts/setup/doctor.sh`

Status: PASS

```text
DOCTOR_OK python runtime
DOCTOR_OK AGENTS.md exists
DOCTOR_OK .codex/config.toml parses
DOCTOR_OK .agents/skills exists
DOCTOR_OK .codex/agents exists
DOCTOR_OK .codex/hooks.json parses
DOCTOR_OK scorecards parse
DOCTOR_OK vault scripts exist
DOCTOR_OK gates scripts exist
DOCTOR_OK autoresearch scripts exist
DOCTOR_PASS repo=/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop
```

### `python3 scripts/gates/run-gates.py --minimal`

Status: PASS

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

`GATES_REPORT_DIR` fallback was not needed.

### `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q`

Status: PASS

```text
361 passed in 69.60s (0:01:09)
```

### `python3 scripts/evals/coding_model_eval.py --mode mock`

Status: PASS

Key output:

```text
status=completed
score=0.9905
route_correctness=1.0
intent_lane_coverage=1.0
brief_contract_coverage=1.0
sensitive_externalization_incidents=0
report_path=/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop/.ralph-codex/reports/evals/coding_model_tasks_latest.json
```

### `bash scripts/validate-ralph-memory-flow.sh`

Status: PASS

```text
25 passed in 0.04s
2 passed in 0.02s
6 passed, 48 deselected in 0.69s
PASS shell lint: validate-ralph-memory-flow.sh
SKIP python lint: Ralph memory flow files (ruff not installed)
SKIP python typecheck: Ralph memory flow files (mypy not installed)
Ralph memory flow validation summary: PASS
```

The script treats missing `ruff` and `mypy` as optional skips, not failures.

## Final Phase Assessment

PASS.

Acceptance criteria status:

- No runtime behavior changed: PASS.
- Baseline report exists: PASS.
- Implementation notes exist: PASS.
- Validation result is documented: PASS.
- Any failure is explained accurately: PASS. The only failure was branch creation, documented above with exact output.

No design or implementation for Ralph Cognitive Memory Tree v2 was performed in this phase.
