# PHASE 01 - Codex-Native Repository Scaffold

Date: 2026-04-27
Repository: `<repo-root>`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_00.md` exists and ends with decision `PASS`.

## Scope

Create the initial Codex-native repository scaffold for `codex-ralph-vault-loop` without copying private vault data or secrets from `multi-agent-ralph-loop`.

## Created / Confirmed Structure

- `README.md`
- `AGENTS.md`
- `.gitignore`
- `pyproject.toml`
- `.codex/config.toml`
- `.codex/hooks.json`
- `.codex/agents/`
- `.codex/hooks/`
- `.agents/skills/`
- `scripts/setup/`
- `scripts/vault/`
- `scripts/memory/`
- `scripts/gates/`
- `scripts/evals/`
- `scripts/cost/`
- `config/scorecards/`
- `docs/architecture/`
- `docs/migration/checkpoints/`
- `docs/evals/`
- `templates/`
- `tests/unit/`
- `tests/integration/`
- `tests/e2e/`

Empty scaffold directories are tracked with `.gitkeep` files.

## Configuration Notes

- Global runtime config inspected: `<codex-config>`.
- Global runtime uses `model_provider = "openai"`.
- Global runtime has no direct Z.ai or MiniMax model-provider blocks.
- Global runtime includes the required MCP dependencies: `ralph_coding_models`, `web-search-prime`, `web-reader`, `zread`, `zai_vision`, and `minimax_coding_tools`.
- Repo-local `.codex/config.toml` uses `model_provider = "openai"` as a safe project template.
- Repo-local `.codex/config.toml` defines the required MCP server entries for subagent/project portability, using environment variable references only.
- Repo-local `.codex/config.toml` does not store MCP secrets.
- Z.ai and MiniMax are not configured as direct `model_provider` entries in either the global runtime config or the repo-local template.
- Z.ai, MiniMax, and `ralph_coding_models` are documented as external/global MCP dependencies already installed in the Codex environment.
- No vault data was copied.
- No API keys, tokens, credentials, cookies, or private key material were added.

## Validation

Commands run:

```bash
git init
find . -maxdepth 3 -type d | sort
python3 - <<'PY'
from pathlib import Path
import tomllib

path = Path(".codex/config.toml")
if path.exists():
    tomllib.loads(path.read_text())
print("PHASE_01_TOML_OK")
PY
```

Additional checks:

- `git init` succeeded and reinitialized the existing repository.
- Required directories check returned `PHASE_01_DIRS_OK`.
- Required files check returned `PHASE_01_FILES_OK`.
- `.codex/hooks.json` parsed as valid JSON.
- Global `<codex-config>` contains no direct Z.ai or MiniMax provider selection and no direct Z.ai or MiniMax model-provider blocks.
- Global `<codex-config>` exposes all required MCPs through `codex mcp list`.
- Repo-local `.codex/config.toml` parses as TOML and declares `web-search-prime`, `web-reader`, `zread`, `zai_vision`, `minimax_coding_tools`, and `ralph_coding_models` without embedding secret values.
- `.gitignore` blocks common secret files, `.env*`, private keys, wallet/keystore material, cookies, and local vault/memory data directories.
- Existing repository history was preserved; this was not recreated destructively.

Gate closure revalidation on 2026-04-27:

- `PHASE_01_DIRS_OK`
- `PHASE_FILES_OK`
- `PHASE_TOML_JSON_OK`
- `GLOBAL_PROVIDER_MCP_OK`
- `LOCAL_PROVIDER_MCP_OK`
- `SCRIPTS_VAULT_TRACKABLE_OK`
- `ralph_coding_models.validate_coding_models`: `all_ok: true`
- Secret/provider scan over changed phase files: clean.

## Risks

- This repository already existed before PHASE 01, so `git init` confirms/reinitializes the existing Git repository instead of creating a brand-new empty repository.
- `.codex/config.toml` includes local MCP declarations with user-specific executable paths for the current workstation; future portability work may replace those with setup-generated paths.
- Runtime MCP secrets remain in environment variables and are not committed to this repository.

## Decision

PASS
