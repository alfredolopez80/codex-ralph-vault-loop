---
name: memory-session
description: Run session-start, active-session, and session-end memory handling for Codex-native Ralph workflows.
---
# Memory Session

## Purpose

Maintain short-lived and durable memory for Codex sessions without depending on Claude-specific runtime primitives.

## Session Start

At session start, read the relevant repo `AGENTS.md`, check the active migration checkpoint, load only the memory needed for the task, and confirm the sensitivity boundary before external MCP use.

## During Work

During work, keep a compact ledger of decisions, commands, validations, and risks. Store transient notes under `~/.ralph-codex` when needed. Use Codex subagents only for independent sanitized work. Treat external model output as advisory until Codex verifies it locally.

## Session End

Write a short sanitized handoff when the work produces durable knowledge:

The handoff should cover task scope, changed files, validation evidence, checkpoint status, risks, follow-ups, and content sensitivity. Keep it short enough for the next session to use quickly.

Do not save RED content. Do not copy raw logs when a summary is enough.

## Output Standard

Memory entries should be factual, short, and useful for the next Codex session.
