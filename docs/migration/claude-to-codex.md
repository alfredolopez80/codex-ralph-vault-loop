# Claude To Codex Migration

The port keeps the Ralph workflow but changes the runtime surface. Codex App and Codex CLI load `AGENTS.md`, `.codex/config.toml`, `.codex/agents/*.toml`, project skills, and global skills from `~/.codex/skills`.

To use the overlay in Codex App, open this repository as the working folder. Confirm that `~/.codex/config.toml` enables `multi_agent` and `codex_hooks`, then restart the app after installing or updating global skills. Run `bash scripts/setup/doctor.sh` as a local smoke test.

The main runtime differences are deliberate. Codex main remains OpenAI-backed and owns final decisions. Z.ai and MiniMax are not configured as completion backends. The migration explicitly rejects direct `model_provider` entries for those vendors because the supported path is MCP tool use with sanitized GREEN or YELLOW context.

Claude concepts that relied on broad team-style coordination or teammate lifecycle events were rewritten as Codex subagents, hooks, gates, ledgers, and handoff files. External model output is advisory. Local implementation happens through Codex main or a narrow coder/tester subagent.

Related phases: [PHASE_02](checkpoints/PHASE_02.md), [PHASE_03](checkpoints/PHASE_03.md), [PHASE_08](checkpoints/PHASE_08.md), [PHASE_15](checkpoints/PHASE_15.md), [PHASE_16](checkpoints/PHASE_16.md).
