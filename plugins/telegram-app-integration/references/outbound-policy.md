# Outbound Policy

Every Telegram response from the target app must pass outbound policy before it reaches the Telegram client.

## Required Checks

- RED hard-block before send.
- Message length bounds.
- Allowed parse mode or plain text fallback.
- Destination chat id must match the authorized event context or an app-owned explicit route.
- Rate limit per chat, user, and command where relevant.
- No raw exception text in user-visible replies.

## RED Hard-Block

Use the target app's sensitive-content detector before every outbound send. Block protected content by default. A warning-only policy is allowed only when the target app documents and tests that choice.

## Formatting

Prefer plain text. If Markdown or HTML formatting is used, escape user-controlled text before interpolation and test malformed input.

## Audit

Audit the outbound decision, method name, target chat id, and sanitized summary. Do not audit raw private text.
