# Claude To Codex Migration

The port keeps the Ralph workflow but changes the runtime surface. Codex App and Codex CLI load `AGENTS.md`, `.codex/config.toml`, `.codex/agents/*.toml`, project skills, and global skills from `~/.codex/skills`.

To use the overlay in Codex App, open this repository as the working folder. Confirm that `~/.codex/config.toml` enables `multi_agent` and `codex_hooks`, then restart the app after installing or updating global skills. Run `bash scripts/setup/doctor.sh` as a local smoke test.

The main runtime differences are deliberate. Codex main remains OpenAI-backed and owns final decisions. Z.ai and MiniMax are not configured as completion backends. The migration explicitly rejects direct `model_provider` entries for those vendors because the supported path is MCP tool use with sanitized GREEN or YELLOW context.

## Runtime Posture

The repository default is `gpt-5.6-luna` with `max` reasoning. This is the
current executor for every turn; routing selects only newly spawned subagents.
Multi-agent work remains enabled with four concurrent threads and one
delegation level.

For implementation at complexity 4-6, Codex main may spawn Terra with high
reasoning. Complexity 7 is a guarded transition with no automatic subagent.
For eligible deep decisions, Sol advisor routing begins at effective complexity
8 with High, XHigh, and Max effort at 8, 9, and 10 respectively. The separate
active-analysis route is read-only, gated, and limited to 9-10. Hooks can
classify and guard spawn arguments; they never switch the current executor or
mutate `config.toml`. See [Model-Level Routing](../model-level-routing.md) for
the complete override, budget, rollout, and rollback contract.

Claude concepts that relied on broad team-style coordination or teammate lifecycle events were rewritten as Codex subagents, hooks, gates, ledgers, and handoff files. External model output is advisory. Local implementation happens through Codex main or a narrow coder/tester subagent.

Related phases: [PHASE_02](checkpoints/PHASE_02.md), [PHASE_03](checkpoints/PHASE_03.md), [PHASE_08](checkpoints/PHASE_08.md), [PHASE_15](checkpoints/PHASE_15.md), [PHASE_16](checkpoints/PHASE_16.md).
