---
name: cost-router
description: Choose the best safe MCP lane across Codex, Z.ai, MiniMax, official MCPs, and local tools using intent, sensitivity, verification value, and then cost.
---
# Cost Router

## Core Rule

Despite the historical name, this skill is now intent-first. Choose the safest useful lane for the task intent; cost is secondary to safety, fit, and Codex-local verification.

Codex main owns decisions, edits, synthesis, and verification. Z.ai and MiniMax are MCP-backed advisors or workers, never direct Codex `model_provider` backends.

## Sensitivity

GREEN covers public docs, public repos, and generic technical prompts. YELLOW covers sanitized project-specific logs, diffs, or specs. RED covers secrets, API keys, credentials, private keys, wallet material, customer data, or sensitive proprietary code.

If content is RED, do not call external MCPs. Use Codex main and local tools only. Do not store that content in repo or vault artifacts.

The requested sensitivity is not trusted blindly. Route decisions must scan the provided context for API keys, JWTs, private keys, seed phrases, wallet material, OAuth tokens, database URLs, `.env` references, and customer-sensitive markers. Detected RED content overrides a GREEN or YELLOW request.

## Intent Lanes

| Intent | Default lane | Use |
|---|---|---|
| Trivial local work | `local` | No external call. |
| Logs, diffs, summaries, PR summaries | `minimax-fast` | Fast compression and first-pass synthesis. |
| Test ideas | `minimax-fast` | Breadth and speed. |
| Lightweight implementation support | `zai-fast` | Small agentic reasoning or command-following. |
| Debugging, architecture, auth, migrations, rollout risk | `zai-deep` | Deep analysis and hypothesis generation. |
| Claim adjudication / reviewer disagreement | `zai-deep` | Verdict with evidence, blocker classification, confidence. |
| Spec vs implementation review | `zai-deep` | Compare implementation to spec/runbook. |
| Current web research | `zai-search` or MiniMax search | Prefer Z.ai for depth; MiniMax for fast lookup. |
| Specific URL reading | `zai-reader` | Public/safe URLs only. |
| Public GitHub repo research | `zai-repo` | Public repos only unless sanitized and explicitly approved. |
| Screenshot, diagram, or chart understanding | `zai-vision` or `minimax-vision` | Analysis only, never generation. |
| RED/sensitive content | `local` | No external MCP. |

For complexity 7 and above, Codex main owns the work with gates. External output can still be advisory when content is GREEN or sanitized YELLOW and the expected verification is clear.

## External MCP Brief

Before sending context to Z.ai or MiniMax for non-trivial work, shape the request as:

```text
EXTERNAL_MCP_BRIEF
tool=<Z.ai|MiniMax>
role=<debug analyst|spec reviewer|claim adjudicator|log summarizer|researcher|vision analyst|implementation advisor>
sensitivity=<GREEN|YELLOW-sanitized>
context_minimized=yes
task=<specific question>
constraints=<what not to change, what assumptions matter>
required_output=
- findings or verdict
- evidence
- confidence
- risks
- recommended next action
codex_final_owner=yes
```

## Routing Decision Protocol

For substantive non-trivial work, record this decision before doing the work or before external delegation:

```text
ROUTE_DECISION
sensitivity=GREEN|YELLOW|RED
intent=<logs|diff|summary|test-ideas|debugging|architecture|spec-review|claim-adjudication|research|repo-reading|url-reading|vision|implementation-support>
complexity=1-10
task_type=<legacy-compatible task type>
route=<local|minimax-fast|zai-fast|zai-deep|zai-search|zai-reader|zai-repo|zai-vision|minimax-vision|codex-subagent|fallback-local>
tool=<optional MCP tool>
reason=<short reason>
verification=<local verification expected>
fallback=<none or reason>
```

Skip the marker only for trivial tasks, RED-local work, explicit user opt-out from external models, unavailable MCPs, or context that cannot be safely sanitized. Missing markers are a warn-only runtime signal during rollout.

## Recordkeeping

When routing externally, record sensitivity, intent, complexity, tool used, and whether Codex verified the result.

Use `scripts/cost/route-task.py` before external delegation, passing `--text` when any context would leave Codex. Use `scripts/cost/redact-for-external.py` before sending sanitized context; it exits non-zero and reports `allowed_external=false` for RED content. Use `scripts/cost/estimate-context.py` for rough context sizing, and `scripts/cost/ledger.py` for JSONL route records that never include raw prompt text or secrets.
