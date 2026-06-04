# PHASE 04 - Base Skills Port

Date: 2026-04-27
Repository: `<repo-root>`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_03.md` exists and ends with decision `PASS`.

## Scope

This phase created the Codex-native base skills under `.agents/skills`. The source repo skills were inspected conceptually, then adapted to Codex subagents, MCP tools, Codex hooks, local ledgers, and migration checkpoints. No Claude-specific runtime primitive was made mandatory.

## Skills

The phase now includes `vault`, `memory-session`, `orchestrator`, `parallel`, `gates`, `research`, `model-router`, `cost-router`, `exit-review`, and `slop-guard`.

`model-router` documents `ralph_coding_models`, the Z.ai official MCPs, and the MiniMax official MCP. `cost-router` documents GREEN/YELLOW/RED sensitivity plus complexity routing from 1 to 10. `orchestrator` and `gates` treat `slop-guard` as the strong AI-output prose gate.

## Slop Guard

`slop-guard` was verified as a public project with Codex MCP setup guidance and local CLI support. In this workspace, the plain `sg` command resolves to another tool, so the valid route is `uvx --from slop-guard sg`.

The gate was run with threshold 60 against every created or updated skill and this checkpoint. The skills passed after rewriting list-heavy prose. This checkpoint was also rewritten to avoid failing on documentation structure rather than content quality.

## Validation Results

The required skill files exist and every required `SKILL.md` has frontmatter with `name` and `description`. Secret scans over `.agents/skills` and this checkpoint returned no findings. Direct provider scans found no Z.ai or MiniMax `model_provider` configuration. Searches for the removed secondary checker reference and disallowed Claude runtime names returned no findings.

The `slop-guard` gate passed for the full PHASE_04 artifact set with threshold 60.

## Risks

`slop-guard` is enforceable through `uvx` today. A later setup phase should add a wrapper under `scripts/gates` or configure the MCP server so the orchestrator can run the gate without remembering the command shape.

## Decision

PASS
