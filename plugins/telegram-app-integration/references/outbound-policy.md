# Outbound Policy

Every Telegram response from the target app must pass outbound policy before it reaches the Telegram client.

See `../snippets/outbound-policy.ts` for an illustrative content/destination safety check. It is not a complete outbound policy; target apps still need rate limits, audit writes, delivery-state handling, and exception-safe replies.

## Required Checks

- RED hard-block before send.
- Non-empty message text and Telegram length bounds.
- Allowed parse mode or plain text fallback.
- Destination chat id must match the authorized event context or an app-owned explicit route.
- Rate limit per chat, user, and command where relevant.
- No raw exception text in user-visible replies.

## RED Hard-Block

Use the target app's sensitive-content detector before every outbound send. Protected content must fail closed and must not be sent to Telegram. Warning-only behavior is acceptable only for non-RED content classes that the target app explicitly approves and tests.

## Formatting

Prefer plain text. If Markdown or HTML formatting is used, escape user-controlled text before interpolation and test malformed input.

## Audit

Audit the outbound decision, method name, pseudonymized chat/user identifiers, and sanitized summary. Do not audit raw private text. Raw identifiers, when needed for delivery or rate limiting, belong in protected operational state with explicit retention and access controls.
