# Security Threat Model

Telegram is an untrusted input boundary. Even allowlisted users can paste malicious content, trigger parser bugs, or accidentally send sensitive data.

## Assets

- Bot API auth material.
- Webhook verification material.
- User, chat, and group allowlists.
- App state touched by Telegram handlers.
- Outbound Telegram messages.
- Audit logs and rate-limit state.
- Attachments, if later enabled.

## P0 Attack Paths

- Forged webhook payload triggers a handler.
- Unauthorized chat or user bypasses access policy.
- Outbound response leaks RED content.
- Group message without mention triggers work by default.
- File handling reads, writes, or sends paths outside the app-owned storage area.

## P1 Attack Paths

- Callback data spoofing triggers an unintended action.
- Command payload reaches shell, SQL, template, or admin policy mutation without validation.
- Log injection hides attacker activity.
- Replay or out-of-order updates corrupt state.
- Dependency confusion compromises Telegram client code used by the app.

## Required Defaults

- Deny by default.
- DM-only by default.
- Groups off by default.
- Text-only Phase 1.
- Attachments default-deny.
- RED hard-block before outbound sends.
- Sanitized structured audit.
- Negative E2E gates before approval.
