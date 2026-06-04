# PHASE 16 Checkpoint - E2E Smoke Test

`docs/migration/checkpoints/PHASE_15.md` was reviewed first. It is marked PASS, so Phase 16 was allowed to proceed.

Orchestrator intake classified this task as GREEN and complexity 2/10. The work was local repo validation. Cost-router and external MCP calls were not used because no external advice was needed.

This phase adds `scripts/setup/doctor.sh`. The script resolves the repo from its own path, so it works from the repo root or another working directory. It selects a Python runtime with `tomllib` and PyYAML before parsing TOML or scorecards. It validates that `AGENTS.md` exists, `.codex/config.toml` parses, `.agents/skills` exists, `.codex/agents` exists, `.codex/hooks.json` parses, scorecards parse, vault scripts exist, and gates scripts exist. It prints `DOCTOR_OK` for each passing check and exits non-zero if any check fails.

Automated coverage was added in `tests/integration/test_doctor_basic.py`. The tests run the doctor from the repo root and from a temporary external directory.

Manual validation:

```text
bash scripts/setup/doctor.sh
python3 scripts/gates/run-gates.py --minimal
test -f docs/migration/checkpoints/PHASE_16.md
```

Results: doctor passed all checks from the repo root and from `/tmp`; minimal gates passed with 1 pass, 2 skips, and 0 failures; the checkpoint exists.

Additional checks:

```text
bash -n scripts/setup/doctor.sh
shellcheck scripts/setup/doctor.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests -q
uvx --from slop-guard sg -t 60 docs/migration/checkpoints/PHASE_16.md
```

Results: shell syntax passed; shellcheck passed; pytest reported `43 passed`; slop-guard scored this checkpoint `84/100`.

Handoff generation used a temporary `RALPH_HOME`, not the production runtime. The generated handoff was `handoffs/latest.md` under that temporary directory.

Vault learning used a temporary `VAULT_DIR`, not the production MiVault. `vault-init.py` initialized the structure, `vault-save.py` stored a YELLOW learning note, and `vault-search.py` found it.

No MCPs were called. No production vault or production Ralph runtime was touched.

Decision: PASS
