# PHASE 15 Checkpoint - Orchestrator Complete

`docs/migration/checkpoints/PHASE_14.md` was reviewed first. It is marked PASS, so Phase 15 was allowed to proceed.

This phase rewrites `.agents/skills/orchestrator/SKILL.md` as the full Codex-native coordination contract. It now covers intake, sensitivity classification, complexity scoring, vault search, cost routing, narrow delegation, local implementation ownership, review depth, gates, evals, vault save rules, RED discard, and handoff.

The orchestrator states that Codex main decides. It integrates `cost-router` through `scripts/cost/route-task.py`, uses `model-router` for MCP selection, and names eval scripts for research, vision, coding model routing, and autoresearch surfaces. It also requires gates before completion.

Delegation is bounded. The skill explicitly says not to launch all subagents by default. It requires a reason for each delegation and keeps Codex main in control of synthesis, file edits, and final completion. GLM-5.1 is documented as a counterpart, not a final decision maker. GLM-5-Turbo and MiniMax-M2.7-highspeed are documented as fast routes for lightweight work.

Global activation was applied with `scripts/setup/install-global-orchestrator-skill.py`. The installed global skill at `<codex-skill-root>/orchestrator/SKILL.md` matches the repo copy.

Manual validation:

```text
grep -n "Codex main decides" .agents/skills/orchestrator/SKILL.md
grep -n "GLM-5.1" .agents/skills/orchestrator/SKILL.md
grep -n "MiniMax-M2.7-highspeed" .agents/skills/orchestrator/SKILL.md
grep -R "TeamCreate\|TeammateIdle\|TaskCompleted" .agents/skills/orchestrator || true
```

Results: the first three commands found the expected policy lines. The legacy runtime grep returned no matches.

Additional checks found no `Claude`, `TeamCreate`, `TeammateIdle`, `TaskCompleted`, or `Task(` references in the orchestrator skill or installer. The global orchestrator copy matches the repo copy byte for byte.

Prose gate:

```text
uvx --from slop-guard sg -t 60 .agents/skills/orchestrator/SKILL.md docs/migration/checkpoints/PHASE_15.md
```

Result: orchestrator score `87/100`; checkpoint score `84/100`.

Security checks were run against the new files. No literal API keys were found. No direct Z.ai or MiniMax `model_provider` configuration was added.

Decision: PASS
