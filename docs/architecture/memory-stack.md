# Memory Stack

The memory stack has three boundaries. Repo files store public configuration, docs, tests, and deterministic scripts. `~/.ralph-codex` stores runtime layers, ledgers, reports, and handoffs. MiVault stores durable human memory outside the public repo.

Layers:

- L0 identity states the core rule: Codex main decides, external models advise, gates verify, vault remembers.
- L1 essential rules keep RED local and require GREEN/YELLOW classification for durable memory.
- L2 project rules capture local operating patterns.
- L3 vault index points into MiVault for deeper recall.
- L4 dream state captures recent high-confidence dream candidates that Codex can use on session start without treating them as canonical rules.

Vault capture uses `scripts/vault/vault-save.py`. GREEN can be global. YELLOW is project-specific. RED is skipped and must not be written to repo, vault, reports, or external tools.

## Dream / Consolidation

`scripts/memory/dream.py` reviews recent handoffs and ledgers, classifies every input, skips RED without printing or storing its raw content, deduplicates repeated learnings, and emits reviewable candidates for L1, L2, and L3.

The command is dry-run by default:

```bash
python3 scripts/memory/dream.py --dry-run
```

It writes `~/.ralph-codex/reports/memory/dream-latest.md`, `~/.ralph-codex/reports/memory/dream-latest.json`, and timestamped archive copies. The first implementation is deterministic and offline; it does not mutate canonical L1/L2/L3 layer files or MiVault by default. Use `--emit-patch` when a copyable layer patch proposal is useful. Candidate application requires a separate approved flow.

Use `--auto-update-state` to write `~/.ralph-codex/layers/L4_dream_state.md` and `.json`. `wakeup.py` loads L4 on future session starts, so Codex can use recent consolidated learnings automatically while keeping them separate from canonical memory. L4 only includes non-duplicate L1/L2/L3 candidates above the confidence threshold.

Use `--vault-inbox` to write a reviewable digest under `~/Documents/Obsidian/MiVault/projects/<project>/inbox/`. This is not canonical MiVault memory; it is an inbox for human/Codex review before promotion.

`scripts/memory/dream-scheduler.py --catch-up` is the non-blocking automation wrapper. The `SessionStart` hook runs it before `wakeup.py` with a default target time of 11:30 local. If the machine was asleep or off, the next Codex session after the target time performs the catch-up; if L4 is fresh, the scheduler is a no-op. Failures are recorded under `~/.ralph-codex/reports/memory/dream-scheduler.json` and do not block session startup.

Spec execution starts in MiVault with `obsidian-spec`. `scripts/vault/obsidian-spec-plan.py` creates a dry-run plan and handoff path before implementation.

Related phases: [PHASE_05](../migration/checkpoints/PHASE_05.md), [PHASE_06](../migration/checkpoints/PHASE_06.md), [PHASE_14](../migration/checkpoints/PHASE_14.md), [PHASE_21](../migration/checkpoints/PHASE_21.md).
