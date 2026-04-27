# Memory Stack

The memory stack has three boundaries. Repo files store public configuration, docs, tests, and deterministic scripts. `~/.ralph-codex` stores runtime layers, ledgers, reports, and handoffs. MiVault stores durable human memory outside the public repo.

Layers:

- L0 identity states the core rule: Codex main decides, external models advise, gates verify, vault remembers.
- L1 essential rules keep RED local and require GREEN/YELLOW classification for durable memory.
- L2 project rules capture local operating patterns.
- L3 vault index points into MiVault for deeper recall.

Vault capture uses `scripts/vault/vault-save.py`. GREEN can be global. YELLOW is project-specific. RED is skipped and must not be written to repo, vault, reports, or external tools.

Spec execution starts in MiVault with `obsidian-spec`. `scripts/vault/obsidian-spec-plan.py` creates a dry-run plan and handoff path before implementation.

Related phases: [PHASE_05](../migration/checkpoints/PHASE_05.md), [PHASE_06](../migration/checkpoints/PHASE_06.md), [PHASE_14](../migration/checkpoints/PHASE_14.md).

