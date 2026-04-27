# PHASE 18 Checkpoint - Optional Global Installation

`docs/migration/checkpoints/PHASE_17.md` was reviewed first. It is marked PASS, so FASE 18 was allowed to proceed.

This phase adds a safe optional global installer for Codex Ralph Vault Loop:

- `scripts/setup/install-global.sh`
- `scripts/setup/uninstall-global.sh`
- `scripts/setup/doctor-global.sh`

The installer creates `~/.agents/skills` and `~/.codex/agents`, then links selected repo skills and optional Codex subagents by symlink. It does not copy vault data, does not copy secrets, and does not edit `~/.codex/config.toml`. Conflicting global entries are moved into `~/.ralph-codex/backups/global-install/<timestamp>/...` before replacement.

Default global skills:

- `orchestrator`
- `model-router`
- `cost-router`
- `gates`
- `vault`
- `memory-session`
- `research`
- `parallel`
- `exit-review`
- `slop-guard`
- `autoresearch`
- `evaluate`
- `scorecard`
- `obsidian-capture`
- `obsidian-spec`

Optional global agents are installed with `--with-agents` and map to the `ralph-*.toml` files under `.codex/agents`.

Validation performed:

```text
bash scripts/setup/install-global.sh --dry-run
bash scripts/setup/doctor-global.sh || true
tmp_home="$(mktemp -d)"
HOME="$tmp_home" bash scripts/setup/install-global.sh --install --with-agents
HOME="$tmp_home" bash scripts/setup/doctor-global.sh
HOME="$tmp_home" bash scripts/setup/uninstall-global.sh --uninstall --with-agents
python3 -m pytest tests/integration/test_global_install_basic.py -q
bash scripts/setup/doctor.sh
python3 scripts/gates/run-gates.py --minimal
shellcheck scripts/setup/install-global.sh scripts/setup/uninstall-global.sh scripts/setup/doctor-global.sh
python3 -m pytest tests -q
```

The real home directory validation used dry-run and doctor only. `doctor-global.sh` correctly reported existing global skills and agents that are not symlinks to this repo; this is expected before the optional real install. The `--install` and `--uninstall` paths were validated with a temporary `HOME`, so the repo local state and real global Codex configuration were not mutated during validation.

Results:

- `install-global.sh --dry-run` passed and printed the planned symlinks/backups.
- Temp `--install --with-agents` passed.
- Temp `doctor-global.sh` passed after install.
- Temp `--uninstall --with-agents` passed.
- `tests/integration/test_global_install_basic.py`: 3 passed.
- `shellcheck`: passed for all global setup scripts.
- Full test suite: 46 passed.
- Minimal gates: passed with 1 passed, 2 skipped, 0 failed.

Security checks:

- No API keys or secret literals were added.
- The installer never writes `~/.codex/config.toml`.
- Uninstall removes only symlinks pointing at this repo.
- Existing global files/directories are backed up before the installer replaces them.

Decision: PASS
