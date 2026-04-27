# Migration Phase Plan

The migration uses checkpoint files as the source of truth. Each phase must read the previous checkpoint, stop if it is missing or not PASS, implement only that phase scope, and write a new checkpoint under `docs/migration/checkpoints`.

Phase groups:

- PHASE_00 to PHASE_03 validate the environment, create the repo, define root instructions, and configure Codex App/CLI without direct external providers.
- PHASE_04 to PHASE_08 port skills, vault scripts, memory scripts, hooks, and subagents.
- PHASE_09 to PHASE_11 add routing, gates, scorecards, and eval infrastructure.
- PHASE_12 to PHASE_14 add AutoResearch, MCP evals, Obsidian capture, and spec-to-implementation planning.
- PHASE_15 and PHASE_16 complete orchestration and run the smoke test.
- PHASE_17 documents the final migration shape.

Operational rule: if a phase affects runtime behavior for future sessions, add a global activation path or record why it remains repo-local. Codex App users should restart after global skill, hook, or subagent changes.

Related checkpoints: [PHASE_00](checkpoints/PHASE_00.md), [PHASE_05](checkpoints/PHASE_05.md), [PHASE_10](checkpoints/PHASE_10.md), [PHASE_15](checkpoints/PHASE_15.md), [PHASE_16](checkpoints/PHASE_16.md).

