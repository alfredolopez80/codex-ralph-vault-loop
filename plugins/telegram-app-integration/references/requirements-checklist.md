# Requirements Checklist

Use this checklist before approving an app-level Telegram integration.

## Runtime And Configuration

- The target app owns webhook or polling runtime.
- The integration names the app-owned Bot API token source without embedding values in source, tests, docs, logs, or snippets.
- Webhook mode validates Telegram's webhook secret token at the app boundary, or uses an authenticated gateway that verifies Telegram and passes a trusted internal assertion.
- Polling mode has offset, retry, and backoff behavior.
- Webhook and polling share the same normalized event contract if both exist.

## Input Handling

- Telegram updates are schema-checked before use.
- Size limits exist before parsing large payloads.
- Raw payloads are not logged.
- Callback data is parsed and scoped before handlers use it.
- Commands are routed through an allowlisted registry.

## Access Policy

- DM-only is the default.
- Groups are disabled unless explicitly required.
- Group mode requires chat allowlist, mention or reply policy, and rate limits.
- User and chat allowlists are checked before handler execution.
- Unauthorized events produce no sensitive response.

## Outbound And Audit

- Outbound text is scanned for RED content before sending.
- Replies are bounded in length and formatting.
- Audit logs are structured and sanitized.
- Audit records include event ids, decisions, and pseudonymized chat/user identifiers, not raw private text.

## Phase 1 Boundary

Phase 1 is text-only. Attachments remain denied until file size, type, storage, scan, retention, and egress controls are defined and tested.
