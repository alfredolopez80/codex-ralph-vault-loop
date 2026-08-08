# MCP capability names and exposure

Phase 13 makes the `zai_*` server names the only active project namespace. A
legacy name remains a migration reference, not a second configured server.
The project does not modify `~/.codex/config.toml`; users with an older global
entry must migrate it deliberately.

## Canonical mapping

| Capability                | Canonical server | Legacy reference   | Tool mapping                                    |
| ------------------------- | ---------------- | ------------------ | ----------------------------------------------- |
| Web search                | `zai_web_search` | `web-search-prime` | `web_search_prime`                              |
| URL reading               | `zai_web_reader` | `web-reader`       | `webReader`                                     |
| Public repository reading | `zai_zread`      | `zread`            | `search_doc`, `get_repo_structure`, `read_file` |

The canonical MCP tool namespaces are therefore:

- `mcp__zai_web_search__web_search_prime`
- `mcp__zai_web_reader__webReader`
- `mcp__zai_zread__search_doc`

The legacy names are retained in this table, historical migration checkpoints,
and legacy `.claude` documents only. They are not active entries in
`.codex/config.toml`.

## Reference inventory

| Location                                                               | Classification         | Action                                                                    |
| ---------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------- |
| `.codex/config.toml`                                                   | active                 | One canonical server per capability; no aliases.                          |
| `scripts/cost/_cost_common.py`                                         | active                 | Routes use canonical server/tool identifiers.                             |
| `scripts/model-router/audit_mcp_servers.py`                            | active                 | Offline and authorized audits use canonical server names.                 |
| Setup and doctor scripts                                               | installer/doctor       | Do not manage user config; validate the repository source namespace.      |
| `.agents/skills/model-router/SKILL.md`                                 | active skill           | Canonical names only; legacy names point here.                            |
| `.agents/skills/research/SKILL.md`                                     | active skill           | Canonical names only.                                                     |
| `.codex/agents/ralph-search-researcher.toml`                           | active agent           | Canonical names only.                                                     |
| `tests/**` and `tests/evals/fixtures/**`                               | test/generated fixture | Canonical expected routes; duplicate and migration fixtures are explicit. |
| `.claude/**`                                                           | legacy/generated       | Kept for Claude migration context; not loaded as Codex MCP configuration. |
| `docs/migration/checkpoints/PHASE_00.md`, `PHASE_01.md`, `PHASE_03.md` | historical             | Preserve prior-state evidence; do not treat as active configuration.      |
| `CLAUDE.md`                                                            | absent                 | No active repository-level CLAUDE.md reference exists.                    |

## Enabled-tool policy

The active project configuration exposes 21 enabled tools across six servers.
Each server's list is unique and justified by an active router, agent, or
analysis fixture. `ui_to_artifact` is not exposed: the project permits
analysis-only visual MCP use and reserves generation for the approved local
image route. Search, URL reading, repository reading, vision analysis, and
coding-model tools remain separate capabilities.

## Verification and migration

Run the offline checker without starting an MCP or contacting a service:

```bash
python3 scripts/model-router/check_mcp_config.py \
  --config .codex/config.toml \
  --migration-doc docs/migration/mcp-tool-names.md \
  --json
```

The checker rejects active aliases, duplicate endpoint identities, duplicate
tool schemas, repeated `enabled_tools`, invalid TOML, and RED-classified
configuration values. It reports counts and names only; it never prints
credential values. `startup_ms` is `null` for offline checks because launching
an MCP or making a network request is outside this phase.

For an old reference, replace the server prefix according to the table above,
then validate the resulting tool name locally. Do not enable both names to
preserve compatibility: the duplicate would expose two schemas for one
capability.
