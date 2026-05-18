# Memory Stack

Ralph Memory has three boundaries:

1. Repo files contain public configuration, docs, tests, and deterministic scripts.
2. `~/.ralph-codex` contains runtime memory, split by active project id.
3. `~/Documents/Obsidian/MiVault` contains durable human memory outside the public repo.

The worktree-aware rule is the foundation:

```text
RALPH_CODE_ROOT != ACTIVE_WORKSPACE_ROOT
```

`RALPH_CODE_ROOT` is the stable checkout recorded in `~/.codex/hooks/.ralph-repo-root`. It tells global hooks where Ralph scripts live. It never defines the active project.

`ACTIVE_WORKSPACE_ROOT` comes from the hook payload `cwd`, tool `workdir`, `PWD`, or the current process. `.codex/hooks/shared/active_context.py` resolves that workspace into git root, project slug, project id, remote hash, branch, sha, session id, and workspace instance id.

Runtime writes now belong under the active project:

```text
~/.ralph-codex/
  projects/
    <project_id>/
      checkpoints/
      handoffs/
      ledgers/
      layers/
      reports/
      cost/
      project.json
  global/
```

Global memory is limited to explicitly global L0/L1 policy. Project runtime memory includes checkpoints, handoffs, ledgers, reports, L2 project rules, L3 vault indexes, and L4 dream state.

Diagrams:

- [Worktree-aware memory architecture](./diagrams/ralph-memory-worktree-architecture.png)
- [Graduation and recall flow](./diagrams/ralph-memory-graduation-recall-flow.png)
- [Interactive visual explainer](./ralph-memory-architecture-explainer.html)

## Layers

- L0 identity states the core rule: Codex main decides, external models advise, gates verify, vault remembers.
- L1 essential rules keep RED local and require GREEN/YELLOW classification for durable memory.
- L2 project rules capture local operating patterns for the active project.
- L3 vault index points into curated MiVault memory for deeper recall.
- L4 dream state captures recent high-confidence dream candidates that Codex can use on session start without treating them as canonical rules.

Vault capture uses `scripts/vault/vault-save.py`. GREEN can be global only when the scope is explicit. YELLOW is project-specific. RED is skipped and must not be written to repo, runtime memory, vault, reports, handoffs, or external tools.

## Continuity And Rehydration

Rolling checkpoints are operational state, not transcript replay. They store objective, phase, verified state, next action, blockers, relevant paths, validation status, and project metadata under:

```text
~/.ralph-codex/projects/<project_id>/checkpoints/
```

`UserPromptSubmit` updates and injects checkpoints only for continuation prompts, and only when the checkpoint belongs to the active project. `PostToolUse` updates the project checkpoint from safe summarized tool metadata. `Stop` compiles matching checkpoints into the project handoff.

Handoff rehydration is gated before it enters context:

- classification must be GREEN or YELLOW.
- project id must match.
- workspace instance id must match when available.
- session metadata must not indicate an unrelated task.
- TTL must be fresh.
- the same handoff hash must not be injected repeatedly.
- the sanitized body must fit the wakeup budget.

The default reinjection budget is `15%` of the wakeup context budget. `wakeup.py` injects the handoff body directly when it fits that ratio. Oversized handoffs are compacted deterministically and remain bounded by `RALPH_REINJECT_HARD_WORD_LIMIT`. Raw frontmatter and transcript-like content are not eligible injected context.

## Dream / Consolidation

`scripts/memory/dream.py` reviews project-scoped handoffs and ledgers, classifies every input, skips RED without printing or storing its raw content, deduplicates repeated learnings, and emits reviewable candidates for L1, L2, and L3. When `--project-id` is provided, every candidate carries source project metadata so later graduation can reject mismatches.

The command is dry-run by default:

```bash
python3 scripts/memory/dream.py --dry-run
```

It writes reports under the active project runtime, for example:

```text
~/.ralph-codex/projects/<project_id>/reports/memory/
```

The first implementation is deterministic and offline; it does not mutate canonical L1/L2/L3 layer files or MiVault by default. Use `--emit-patch` when a copyable layer patch proposal is useful. Candidate application requires a separate approved flow.

Use `--auto-update-state` to write the project `layers/L4_dream_state.md` and `.json`. `wakeup.py` loads project L4 on future session starts, so Codex can use recent consolidated learnings automatically while keeping them separate from canonical memory. L4 only includes non-duplicate L1/L2/L3 candidates above the confidence threshold.

Use `--assist-promote` to let Ralph Memory promote only high-confidence, runtime-corroborated L2/L3 candidates into runtime canonical layers and queue ambiguous, L1, Codex memory, Claude import, and `.local-notes/` candidates for review when they are not sufficiently corroborated. The promotion path writes `reports/memory/promotion-latest.{json,md}` and `promotion-events.jsonl`. It does not write to `~/.codex/memories` or source `.local-notes/`, and RED inputs remain skipped. The Stop hook runs this assisted promotion path and emits a warning when review candidates should be shown to the user instead of silently becoming canonical.

Use `--vault-inbox` to write a reviewable digest under `~/Documents/Obsidian/MiVault/projects/<project>/inbox/`. This is not canonical MiVault memory; it is an inbox for human/Codex review before promotion.

`scripts/memory/dream-scheduler.py --catch-up` is the non-blocking automation wrapper. The `SessionStart` hook runs it before `wakeup.py` with a default target time of 11:30 local. If the machine was asleep or off, the next Codex session after the target time performs the catch-up; if L4 is fresh, the scheduler is a no-op. Failures are recorded under `~/.ralph-codex/reports/memory/dream-scheduler.json` and do not block session startup.

## MiVault Graduation

MiVault has two trust zones:

- `projects/<project>/inbox` and `raw` are quarantine. They are not canonical memory.
- `projects/<project>/{wiki,decisions,sessions,handoffs}` and curated global `wiki/decisions` are recall-eligible when relevant.

`scripts/vault/vault-inbox-review.py` and `scripts/vault/vault-graduate.py` implement the graduation path. Review is report-only unless apply is explicit. Each decision includes classification, candidate hash, source project metadata, target, confidence, decision, and an `aristotle` rationale block.

Decision rules:

- RED: skip with hash-only safe audit metadata.
- duplicate: skip.
- missing project source for project memory: ask user.
- source project mismatch: skip.
- global or L1 rule: ask user.
- high-confidence project decision: graduate to `decisions`.
- high-confidence project knowledge: graduate to `wiki`.
- ambiguous or low-confidence memory: ask user or skip.

## Recall Defaults

`scripts/memory/ralph-recall.py` reads context as assistance, not authority. Explicit user instructions and current repo files win.

Default recall sources:

- repo `AGENTS.md` and repo-local skills.
- active project runtime layers, handoffs, and ledgers under `~/.ralph-codex/projects/<project_id>/`.
- curated MiVault project `wiki`, `decisions`, `sessions`, and `handoffs`.
- curated MiVault global `wiki` and `decisions`.

Excluded by default:

- MiVault inbox and raw areas.
- ambiguous legacy runtime memory.
- files classified RED or paths that look secret-bearing.

Use `--include-raw` only for explicit diagnostics. It may include inbox/raw candidates, but those candidates still are not canonical memory and still pass output safety filtering.

Spec execution starts in MiVault with `obsidian-spec`. `scripts/vault/obsidian-spec-plan.py` creates a dry-run plan and handoff path before implementation.

Related phases: [PHASE_05](../migration/checkpoints/PHASE_05.md), [PHASE_06](../migration/checkpoints/PHASE_06.md), [PHASE_14](../migration/checkpoints/PHASE_14.md), [PHASE_21](../migration/checkpoints/PHASE_21.md).
