# PHASE 00 - Base Environment and MCP Validation

Date: 2026-04-26
Repository checked: `/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop`
Requested phase scope: validate Codex environment readiness for a Codex-native migration.

## Previous Checkpoint

No previous checkpoint is required for PHASE 00.

## Active Codex Configuration

- Active config inspected: `/Users/alfredolopez/.codex/config.toml`
- Local repo config expected by the target tree was not present at `.codex/config.toml`.
- Native orchestrator provider: `model_provider = "openai"`
- Native orchestrator model: `gpt-5.5`
- Direct Z.ai or MiniMax provider usage: not detected in the active config.
- `[model_providers.*]` direct provider blocks for Z.ai or MiniMax: not detected in the active config.
- Secrets/API keys were not printed or copied into this checkpoint.

## MCPs Detected

Detected in active Codex config:

| Expected MCP | Config status | Runtime/tool status observed |
|---|---:|---|
| `ralph_coding_models` | Present | Available as `mcp__ralph_coding_models__` |
| `zai_web_search` | Present | Remote endpoint responds; legacy-compatible alias retained |
| `web-search-prime` | Present | Added canonical alias for Z.ai search MCP; `codex mcp get web-search-prime` reports `streamable_http` + bearer token auth |
| `zai_web_reader` | Present | Remote endpoint responds; legacy-compatible alias retained |
| `web-reader` | Present | Added canonical alias for Z.ai reader MCP; `codex mcp get web-reader` reports `streamable_http` + bearer token auth |
| `zai_zread` | Present | Remote endpoint responds; legacy-compatible alias retained |
| `zread` | Present | Added canonical alias for Z.ai repo-reader MCP; `codex mcp get zread` reports `streamable_http` + bearer token auth |
| `zai_vision` | Present | Available as `mcp__zai_vision__` |
| `minimax_coding_tools` | Present | Available as `mcp__minimax_coding_tools__`; smoke call to `web_search` succeeded |

Additional MCPs/plugins observed in active config include `context7`, `filesystem`, `playwright`, `web-search`, `chrome_devtools`, `mermaid`, `nanobanana`, and several Codex app plugins.

## Tools Detected

`ralph_coding_models`:

- `validate_coding_models`
- `ensemble_counterpart`
- `minimax_agentic_fast`
- `route_coding_task`
- `zai_coding_deep`
- `zai_coding_fast`
- `minimax_agentic`

`zai_vision`:

- `analyze_image`
- `diagnose_error_screenshot`
- `extract_text_from_screenshot`
- `analyze_data_visualization`
- `ui_diff_check`
- `understand_technical_diagram`
- `analyze_video`
- `ui_to_artifact`

`minimax_coding_tools`:

- `web_search`
- `understand_image`

`web_search` fallback/real exposed name:

- `search`
- `fetchWebContent`
- `fetchGithubReadme`
- `fetchCsdnArticle`
- `fetchLinuxDoArticle`
- `fetchJuejinArticle`

Z.ai canonical aliases added to active Codex config:

- `web-search-prime`: expected namespace on reload is `mcp__web_search_prime__`.
- `web-reader`: expected namespace on reload is `mcp__web_reader__`.
- `zread`: expected namespace on reload is `mcp__zread__`.

## `validate_coding_models` Result

Result: all required coding model routes passed.

| Route | Provider | Model | Status |
|---|---|---|---|
| `zai_deep` | Z.ai | `glm-5.1` | OK |
| `zai_fast` | Z.ai | `glm-5-turbo` | OK |
| `minimax_fast` | MiniMax | `MiniMax-M2.7-highspeed` | OK |

Summary flags:

- `zai_deep_ok`: true
- `zai_fast_ok`: true
- `minimax_fast_ok`: true
- `all_ok`: true

## Required Model Availability

- GLM-5.1: present and validated.
- GLM-5-Turbo: present and validated.
- MiniMax-M2.7-highspeed: present and validated.

## Environment Variable Presence

Required Z.ai and MiniMax environment variables were checked for presence only; values were not printed.

- `Z_AI_API_KEY`: set.
- `Z_AI_MODE`: set.
- `MINIMAX_API_KEY`: set.
- `MINIMAX_API_HOST`: set.
- Z.ai coding/router model variables: set.
- MiniMax router model/base URL variables: set.

## Risks

- The user request said "repo actual multi-agent-ralph-loop", while the active writable repository is `codex-ralph-vault-loop`. This checkpoint was created in the active target repo.
- `.codex/config.toml` is absent in this repo; validation used the active global Codex config at `/Users/alfredolopez/.codex/config.toml`.
- This running Codex conversation was initialized before the canonical aliases were added, so tool discovery in this same session may not show the new namespaces until Codex App/CLI reloads MCP configuration.

## Decision

PASS

The core migration precondition is met: Codex remains on OpenAI as the native orchestrator, Z.ai/MiniMax are not configured as direct providers, the required coding model routes validate successfully through MCP tooling, and the Z.ai remote MCPs now have canonical aliases configured for the next Codex App/CLI reload.
