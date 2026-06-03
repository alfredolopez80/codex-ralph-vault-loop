# E2E And Security Gates

Use these gates when reviewing or implementing Telegram Bot API inside a target app.

## Positive Gate

The happy path must start at the app-owned entrypoint, not an internal helper:

1. Webhook mode sends an HTTP request to the registered app route with the expected inbound verification material, or polling mode runs the app-owned polling worker against a fake Telegram provider boundary.
2. The app validates and normalizes the update.
3. Access policy allows the event.
4. The intended handler runs.
5. Outbound policy approves the response.
6. The Telegram client abstraction receives the expected method, chat id, and payload.
7. Durable app evidence is produced, such as persisted state, a domain event, a queued outbound action, polling offset state, policy decision record, or sanitized audit row.

Evidence must include a real entrypoint signal, durable business evidence, outbound method details, and a sanitized audit record. Handler return values can support unit or integration tests, but they do not satisfy the positive E2E gate by themselves.

## Mock Boundary

E2E and app-integration gates may fake Telegram as the external provider. They must not stub app-owned inbound verification, normalization, access policy, handler routing, outbound policy, audit writes, or polling offset state.

Do not accept direct calls to normalizers, route internals, polling helpers, handlers, or outbound policy as happy-path E2E substitutes.

## Negative Gates

Required negative cases:

- forged webhook rejected;
- malformed update rejected;
- non-allowlisted DM blocked;
- group message blocked by default;
- group message without mention blocked when group mode is enabled;
- unauthorized callback data blocked;
- command payload cannot mutate admin policy by default;
- outbound RED-looking text blocked;
- log injection attempt sanitized;
- attachment attempts denied in Phase 1;
- duplicate or stale polling update does not re-run handlers or resend;
- out-of-order polling update is rejected or safely sequenced;
- polling offset advances only after successful processing according to the app contract;
- retry after handler or outbound failure does not duplicate irreversible app effects;
- backoff is deterministic and testable without fixed sleeps.

## Review Verdict

Do not approve an implementation if tests only call handlers, normalizers, route internals, polling helpers, or outbound policy directly and skip the app-owned entrypoint, inbound validation, access policy, outbound policy, durable evidence, polling state, or audit behavior.
