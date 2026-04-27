# PHASE 17 Checkpoint - Migration Documentation

`docs/migration/checkpoints/PHASE_16.md` was reviewed first. It is marked PASS, so FASE 17 was allowed to proceed.

This phase adds the final migration and architecture docs. The migration set is `docs/migration/source-map.md`, `docs/migration/claude-to-codex.md`, and `docs/migration/phase-plan.md`. The architecture set is `docs/architecture/overview.md`, `docs/architecture/memory-stack.md`, `docs/architecture/mcp-model-router.md`, `docs/architecture/subagents.md`, `docs/architecture/hooks.md`, `docs/architecture/evaluation-spine.md`, and `docs/architecture/threat-model.md`.

The source map covers every required mapping. `CLAUDE.md` maps to `AGENTS.md`; `.claude/skills` maps to `.agents/skills`; Claude hooks map to Codex hooks; Agent Teams map to `.codex/agents`; vault L3 maps to MiVault; AutoResearch maps to scorecard-driven AutoResearch; research maps to official MCPs plus `ralph_coding_models`; direct MiniMax/Z.ai providers are discarded.

The docs explain Codex App usage, checkpoint links, global activation expectations, memory boundaries, hooks, subagents, MCP routing, eval coverage, and threat controls. They state that there is no `model_provider directo` for Z.ai or MiniMax. They also state that Z.ai and MiniMax are not used for visual generation and that GPT Imágenes 2 is the approved image generation route.

Manual validation:

```text
find docs -type f | sort
grep -R "model_provider directo" docs/migration docs/architecture
grep -R "GPT Imágenes 2" docs/architecture AGENTS.md
```

Results: all required docs exist; `model_provider directo` appears in migration and architecture docs; `GPT Imágenes 2` appears in architecture docs. Additional checks confirmed that new docs link to checkpoint phases and explain Codex App usage.

Security checks found no literal API keys in the new docs. `bash scripts/setup/doctor.sh` passed, and `python3 scripts/gates/run-gates.py --minimal` passed with zero failures.

Decision: PASS
