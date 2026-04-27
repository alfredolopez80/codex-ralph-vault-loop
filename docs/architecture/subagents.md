# Subagents

Subagents are narrow Codex workers defined in `.codex/agents/*.toml` and installed globally when needed. They are not broad teammates that run by default.

Rules:

- Do not launch all subagents by default.
- Give each subagent a bounded task, write scope, and expected output.
- Prefer read-only roles for review, research, security, and vision analysis.
- Use coder/tester roles for local repo changes when delegated work is useful.
- Codex main integrates results and decides completion.

External model subagents are MCP-aware, not direct provider profiles. RED content is never sent to them.

Related phases: [PHASE_08](../migration/checkpoints/PHASE_08.md), [PHASE_15](../migration/checkpoints/PHASE_15.md).

