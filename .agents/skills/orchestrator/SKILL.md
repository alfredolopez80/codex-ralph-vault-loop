---
name: orchestrator
description: Coordinate Codex main across subagents, MCP tools, vault memory, gates, evals, and handoffs.
---

# Orchestrator

## Core Contract

Codex main decides. External models advise. Gates verify. Vault remembers.

The orchestrator is the routing contract for complex work. Use the smallest helper set that reduces risk or latency. Every delegation needs a short reason that names the task, sensitivity, complexity, expected output, and safety boundary.

## Required Flow

Use this sequence for non-trivial work. Step 1 is intake: restate the task, scope, acceptance criteria, repo target, and checkpoint requirement. Step 2 is sensitivity classification as GREEN, YELLOW, or RED; RED stays local, is never externalized, and is never saved. Step 3 is complexity scoring from 1 to 10, which selects direct work, a Codex subagent, or advisory MCP support. Step 4 is vault search when prior decisions, specs, handoffs, or reusable learning may affect the task. Only use safe GREEN or YELLOW summaries from the vault.

Step 5 is cost-router. Use `scripts/cost/route-task.py` or the `cost-router` skill before substantive non-trivial work and before any external delegation. Record a visible `ROUTE_DECISION` block or ledger entry with sensitivity, complexity, task type, route, reason, and fallback. Step 6 is route choice: direct Codex work, a narrow Codex subagent, `ralph_coding_models`, official Z.ai MCPs, or official MiniMax MCPs. Step 7 is local implementation through Codex main or a coder/tester subagent with repo write permission. MCP output is advisory or bounded worker output; Codex integrates it and verifies behavior.

Step 8 is risk-based review with tests and security checks. Step 9 is gates before completion; use `scripts/gates/run-gates.py` where applicable, plus targeted parse, lint, test, secret, and `slop-guard` checks. Step 10 is eval execution when the work touches routing, research, vision, memory, cost, or autoresearch behavior. Step 11 saves durable GREEN or YELLOW learning to the vault when useful; the note must be concise and sanitized. Step 12 discards RED working context after the task and writes none of it to repo, vault, reports, or external tools. Step 13 is the handoff with changed files, validation evidence, route decisions, residual risks, and PASS or FAIL.

## Delegation Rules

Do not launch all subagents by default. Spawn only the specific subagent that owns a bounded slice. Give it an explicit write scope or make it read-only. Codex main keeps final control of edits and final synthesis.

Subagents use approval relay by default. They should not request sandbox or network approval directly unless Codex main explicitly assigned that behavior. If a subagent needs an escalated command, installation, network access, or another sensitive action, it returns `APPROVAL_NEEDED` with agent, command, reason, risk, and suggested prefix rule, then stops for Codex main to decide.

Use `model-router` for MCP selection. GLM-5.1 is a counterpart for medium or high-complexity analysis such as debugging, architecture review, or design review. It is never the final decision maker. GLM-5-Turbo and MiniMax-M2.7-highspeed are fast routes for lightweight command following, logs, diffs, summaries, and test ideas.

Use official Z.ai MCPs for current search, page reading, repo reading, and vision analysis. Use official MiniMax MCPs for fast search or quick image understanding. Never use Z.ai or MiniMax for image, video, audio, voice, or music generation. GPT Images 2 is the only approved image generation route.

If content is RED, use Codex main and local tools only. If a preferred MCP is unavailable, continue locally when safe and record the degraded route.

## Gates And Evals

Gates are mandatory before claiming completion. For code changes, run the smallest reliable test first, then broader tests when the blast radius warrants it. For docs and checkpoint text, run `slop-guard` or record a local prose review fallback.

Run eval scripts for behavior that affects eval-covered surfaces: `scripts/evals/research_eval.py`, `scripts/evals/vision_eval.py`, `scripts/evals/coding_model_eval.py`, `scripts/evals/autoresearch_dry_run.py`, and scorecard tools when relevant.

## Stop Conditions

Stop if the previous checkpoint is missing or not PASS, if safe validation cannot be performed, if the requested route requires RED externalization, if secrets would be exposed, or if gates fail without an accepted mitigation.
