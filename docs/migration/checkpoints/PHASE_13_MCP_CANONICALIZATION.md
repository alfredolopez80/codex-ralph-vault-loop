# PHASE 13 - MCP exposure canonicalization

Date: 2026-08-08
Repository: `codex-ralph-vault-loop`

## Previous checkpoint

`docs/migration/checkpoints/PHASE_12.md` exists and is marked `PASS`.

The older MCP-evaluation checkpoint at `PHASE_13.md` remains historical; this
checkpoint records the runtime-token optimization phase with the same number.

## Aristotle first-principles record

### 1. Autopsia de suposiciones

The configuration assumed that keeping canonical and legacy names active was a
safe compatibility mechanism. With identical endpoints and enabled tools it
actually exposes duplicate server and tool schemas. The broad vision list also
included `ui_to_artifact` even though this workflow permits analysis, not
external visual generation.

### 2. Verdades irreductibles

One capability must have one active server namespace; legacy migration text is
not an active compatibility surface. Search, URL reading, repository reading,
vision analysis, MiniMax analysis, and coding-model tools remain distinct. RED
content stays local, no direct external model provider is added, and user-level
configuration is not rewritten by this repository.

### 3. Reconstrucción desde cero

The active project config now contains six servers and 21 unique enabled tool
entries: `zai_web_search`, `zai_web_reader`, `zai_zread`, `zai_vision`,
`minimax_coding_tools`, and `ralph_coding_models`. The three legacy server
entries are removed. `ui_to_artifact` is removed from the analysis-only vision
surface.

### 4. Mapa suposición vs verdad

`docs/migration/mcp-tool-names.md` records every active, documentation,
legacy, test, and historical reference, plus the exact canonical mapping and
the no-duplicate rule.

### 5. Movimiento Aristotélico

`scripts/model-router/check_mcp_config.py` performs an offline, mockable audit
for TOML validity, duplicate endpoints/schemas, repeated tools, active aliases,
project/global semantic parity, and classified configuration values. Repo and
global doctor/smoke paths invoke it without starting MCPs or making network
calls.

## Implementation

- `.codex/config.toml` has one active server per canonical Z.ai capability.
- Active skills, agents, routing code, and fixtures use canonical names.
- Added `docs/migration/mcp-tool-names.md` and the offline checker.
- `scripts/setup/doctor.sh`, `doctor-global.sh`, and
  `smoke-global-hooks.py` now report canonical MCP exposure.
- No global configuration was installed or edited.

## Metrics

| Metric                    |               Before |  After |
| ------------------------- | -------------------: | -----: |
| Configured servers        |                    9 |      6 |
| Enabled tool entries      |                   27 |     21 |
| Estimated exposed schemas |                   27 |     21 |
| Config bytes              |                3,094 |  2,445 |
| Startup impact            | not measured offline | `null` |

## Checks

- Canonicalization tests use temporary TOML fixtures and mocks.
- `doctor.sh` reports canonical unique exposure.
- Startup timing remains intentionally unmeasured offline.

Decision: PASS
