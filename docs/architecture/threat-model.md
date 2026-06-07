# Threat Model

This threat model covers the public repository, the local Codex runtime it
installs, and the MCP advisory boundaries it configures. It separates published
source files from local runtime state. Runtime state belongs outside the repo.

## System Model

| Component            | Evidence                                      | Role                                                                                  |
| -------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------- |
| Project instructions | `AGENTS.md`, `README.md`                      | Define Codex behavior and public operating contract.                                  |
| Codex project config | `.codex/config.toml`                          | Declares local defaults and MCP server entries.                                       |
| Hooks                | `.codex/hooks`, `.codex/hooks.json`           | Classify prompts, guard tool use, capture bounded state, and stop unsafe persistence. |
| Skills and agents    | `.agents/skills`, `.codex/agents`             | Provide reusable workflows and bounded subagent roles.                                |
| Local scripts        | `scripts/`                                    | Run setup, gates, evals, memory, vault, route, and safety checks.                     |
| Runtime memory       | `~/.ralph-codex`                              | Stores local ledgers, checkpoints, reports, and handoffs outside the repo.            |
| Curated vault        | external vault path                           | Stores reviewed durable knowledge outside the repo.                                   |
| MCP advisors         | `.codex/config.toml`, `scripts/model-router/` | Advise through tool boundaries after sensitivity checks.                              |

Out of scope: hosted production infrastructure, private vault contents, and
third-party MCP service internals.

## Trust Boundaries

| Boundary                     | Direction                      | Existing control                                                                |
| ---------------------------- | ------------------------------ | ------------------------------------------------------------------------------- |
| User prompt to Codex hooks   | local input                    | prompt classification, route decision, context budget guard.                    |
| Codex to local shell         | local command execution        | PreTool guard, SFW package-manager policy, repo boundary checks.                |
| Codex to MCP advisors        | local to remote tool           | GREEN/YELLOW-only routing, RED local-only policy, Codex synthesis after advice. |
| Hooks to runtime memory      | repo context to local state    | path scoping, RED skip, atomic checkpoint writes, project identity gates.       |
| Runtime memory to recall     | local state to prompt context  | TTL, scope, branch/session/workspace checks, size budget, dedupe.               |
| Vault inbox to curated vault | quarantine to durable recall   | review and graduation workflow before default recall.                           |
| Public repo to user machines | cloned source to local install | install scripts use dry-run, backups, and worktree-source refusal.              |

## Assets

- Repository source integrity.
- Codex instruction integrity.
- MCP route integrity.
- Local runtime state under `~/.ralph-codex`.
- External curated vault state.
- Hook reports, gate reports, and eval evidence.
- Public documentation accuracy.

## Attacker Capabilities

| Capability                          | Notes                                                                       |
| ----------------------------------- | --------------------------------------------------------------------------- |
| Opens a public issue or PR          | Can attempt prompt injection through docs, examples, or suggested commands. |
| Modifies repo files in a PR         | Can try to weaken hooks, config, routing, docs, or tests.                   |
| Runs the installer locally          | Can misconfigure a checkout or run from an unsafe worktree.                 |
| Triggers MCP routes through prompts | Can try to move unsafe context across an external boundary.                 |
| Reads public repo history           | Can inspect committed paths, examples, reports, and docs.                   |

Non-capabilities assumed here: direct access to the maintainer machine, local
runtime state, environment values, or private vault contents.

## Prioritized Threats

| Priority | Threat                                                                             | Likelihood | Impact | Existing mitigation                                             | Recommended follow-up                                                                       |
| -------- | ---------------------------------------------------------------------------------- | ---------- | ------ | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| High     | Published local path or maintainer-only config reveals private workstation layout. | Medium     | Medium | Public-readiness grep, `.gitignore`, repo-local config cleanup. | Keep path scans in release checklist and avoid absolute maintainer paths in docs/config.    |
| High     | RED material is routed to a remote MCP advisor.                                    | Low        | High   | Sensitivity detector, route policy, MCP boundary docs, tests.   | Keep detector coverage for new content classes and require route traces for high-risk work. |
| High     | Hook or installer change weakens local safety.                                     | Medium     | High   | Hook contract tests, global smoke tests, pre-global audit.      | Treat hook changes as security-sensitive and run full hook validation before merge.         |
| Medium   | Test fixture or example trips public scanners and hides a real issue in noise.     | Medium     | Medium | Semgrep, gitleaks, sensitive detector tests.                    | Keep examples scanner-clean unless the test explicitly proves detection.                    |
| Medium   | Prompt injection through docs or skills changes Codex behavior after install.      | Medium     | Medium | Codex main ownership, skill review, gates, source lineage docs. | Review new skills with writing-skills and security review before global install.            |
| Medium   | Runtime memory from one project is recalled in another project.                    | Low        | High   | project_id, branch/session/workspace checks, recall tests.      | Continue requiring selected memory trace or explicit fallback in memory work.               |
| Low      | Public docs overstate validation or current status.                                | Medium     | Low    | README validation commands, checkpoints, gates.                 | Keep README status factual and tied to runnable commands.                                   |

## Current Review Notes

- `gitleaks detect --no-banner --redact` passed on the current repository.
- Semgrep with repo-local rules found one scanner-noise example in a legacy
  `.claude` agent. The example was rewritten to avoid a misleading match while
  preserving the signing concept.
- The repo had maintainer-local absolute paths in config, scripts, docs, and
  learned-rule source notes. Those were removed or replaced with portable
  references before publication.
- This repo does not contain blog-post or locale folders today. Future content
  should follow the README content quality checklist before publishing.

## Open Assumptions

- GitHub Security Advisories are available for vulnerability intake.
- Public users will clone the repo and run scripts locally; there is no hosted
  service boundary in this repo.
- MCP keys and provider configuration remain environment-managed and are not
  committed.

Related docs: [MCP model router](./mcp-model-router.md),
[Memory stack](./memory-stack.md), [Hooks](./hooks.md),
[Evaluation spine](./evaluation-spine.md), and [Security policy](../../SECURITY.md).
