# PHASE 14 Checkpoint - Obsidian Spec Capture

`docs/migration/checkpoints/PHASE_13.md` was reviewed first. It is marked PASS, so FASE 14 was allowed to proceed.

This phase adds two Codex-native vault skills. `obsidian-capture` records safe decisions, bugs, fixes, and lessons in MiVault. `obsidian-spec` turns a vault spec note into a dry-run implementation plan before any repository code is edited.

The new vault templates live in `templates/vault`. `vault-init.py` now copies them into the vault `_templates` folder. The template set covers concepts, decisions, sessions, handoffs, autoresearch results, and specs.

The new script `scripts/vault/obsidian-spec-plan.py` reads a Markdown spec note, blocks RED specs, extracts objective, scope, and acceptance criteria, then writes a plan into the vault handoffs folder. The script is dry-run by default and records that no repository code was modified.

Global activation was applied through `scripts/setup/install-global-obsidian-skills.py`. The installed global skills match the repo copies at `/Users/alfredolopez/.codex/skills/obsidian-capture` and `/Users/alfredolopez/.codex/skills/obsidian-spec`.

Global execution was also tested from `/tmp` with absolute paths to this repo, not from the repository working directory. The global test initialized a temporary vault, copied templates, saved a YELLOW note, found it with vault search, and generated `projects/global-phase14/handoffs/demo-global-spec-plan.md` from a vault spec.

Manual validation used a temporary `VAULT_DIR`.

```text
python3 scripts/vault/vault-init.py
python3 scripts/vault/vault-save.py --classification YELLOW --text "Spec-to-implementation test"
python3 scripts/vault/vault-search.py "Spec-to-implementation"
python3 scripts/vault/obsidian-spec-plan.py --spec <temp-vault>/projects/codex-ralph-vault-loop/wiki/demo-spec.md
```

Results: templates were copied to `_templates`; YELLOW capture saved a project note; GREEN capture saved a global note; search found the saved YELLOW text; the demo spec produced `projects/codex-ralph-vault-loop/handoffs/demo-spec-plan.md`.

Automated validation:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests -q
```

Result: `41 passed`.

Prose gate used `uvx --from slop-guard sg -t 60` on this checkpoint and the two new skills. Result: all three files passed.

Security checks were run against the new files. No literal API keys were found. No direct Z.ai or MiniMax `model_provider` configuration was added. RED specs are blocked by `obsidian-spec-plan.py`, and `vault-save.py` continues to skip RED capture.

Decision: PASS
