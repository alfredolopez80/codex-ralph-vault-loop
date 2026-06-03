---
name: telegram-app-integration
description: Guide Codex when an existing application needs Telegram Bot API integration without making Codex or this plugin the runtime.
user-invocable: true
argument-hint: "[target app path, Telegram integration request, or review scope]"
---

# Telegram App Integration

Use this skill when a target application needs to receive or send Telegram Bot API traffic. The skill is guidance for implementation and review inside that target app. It does not create a Telegram app, create a bot, register webhooks, store live auth values, expose a port, or start workers.

## Ground Rules

- The target app owns webhook handlers, polling workers, state, outbound calls, deploy configuration, and runtime operation.
- Codex may edit the target app only when the user asks for implementation in that app.
- This plugin provides requirements, threat model, contracts, snippets, and gates.
- `claude/channel`, Codex-to-Telegram bridges, `codex-telegram`, and `telegram-service-kit` are out of scope.
- Phase 1 is text-only. Attachments stay default-deny until text-only security and E2E gates exist.

## Workflow

1. Identify the target app and its runtime pattern before proposing changes.
2. Decide webhook, polling, or both using `references/telegram-bot-api-model.md`.
3. Check requirements with `references/requirements-checklist.md`.
4. Apply the threat model in `references/security-threat-model.md`.
5. Shape app-level events and handlers with `references/handler-contract.md`.
6. Enforce outbound policy from `references/outbound-policy.md`.
7. Keep attachments denied unless `references/attachment-policy.md` is satisfied.
8. Require real and negative gates from `references/e2e-gates.md`.

## Expected Output

For reviews, return: verdict, missing requirements, security risks, required gates, and app-owned files likely involved.

For implementation, keep changes inside the target app. Do not add this plugin as a runtime dependency. Do not include live auth values or commands that create external Telegram resources.
