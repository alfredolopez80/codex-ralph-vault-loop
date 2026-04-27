# PHASE 03 - Codex App CLI Configuration

Date: 2026-04-27
Repository: `/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_02.md` exists and ends with decision `PASS`.

## Scope

Create `.codex/config.toml` compatible with Codex App/CLI.

## Configuration

`.codex/config.toml` includes:

- `model = "gpt-5.5"`
- `model_provider = "openai"`
- `model_reasoning_effort = "high"`
- `[features] multi_agent = true`
- `[features] codex_hooks = true`
- `[agents] max_threads = 6`
- `[agents] max_depth = 1`
- `[agents] job_max_runtime_seconds = 900`

External model policy:

- No `[model_providers.zai]`.
- No `[model_providers.minimax]`.
- No `profiles.zai_*`.
- No `profiles.minimax_*`.
- Z.ai and MiniMax remain MCP tools, not direct Codex providers.

MCP dependencies declared with environment variable references only:

- `ralph_coding_models`
- `zai_web_search`
- `zai_web_reader`
- `zai_zread`
- `zai_vision`
- `minimax_coding_tools`

Compatibility aliases also declared:

- `web-search-prime`
- `web-reader`
- `zread`

## Validation

Manual validation commands:

```bash
python3 - <<'PY'
from pathlib import Path
import tomllib
tomllib.loads(Path(".codex/config.toml").read_text())
print("CONFIG_TOML_OK")
PY

grep -R "Z_AI_API_KEY =" .codex || true
grep -R "MINIMAX_API_KEY =" .codex || true
grep -R "\[model_providers.zai\]" .codex/config.toml || true
grep -R "\[model_providers.minimax\]" .codex/config.toml || true
```

Additional automated checks:

- `.codex/config.toml` parsed with Python `tomllib`.
- No literal API keys were found in `.codex`.
- No direct Z.ai/MiniMax provider blocks were found.
- No Z.ai/MiniMax profiles were found.
- Required MCP server entries are present.

## Risks

- The project config includes current workstation paths for `ralph_coding_models`; future setup automation should generate or validate those paths.
- Secrets are intentionally referenced through environment variable names only.

## Decision

PASS
