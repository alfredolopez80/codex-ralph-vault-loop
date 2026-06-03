# E2E And Security Gates

Use these gates when reviewing or implementing Telegram Bot API inside a target app.

## Positive Gate

The happy path must start at the app boundary:

1. A Telegram update fixture enters webhook or polling code.
2. The app validates and normalizes the update.
3. Access policy allows the event.
4. The intended handler runs.
5. Outbound policy approves the response.
6. The Telegram client abstraction receives the expected method, chat id, and payload.
7. Audit records sanitized metadata.

Evidence must include app state or handler result, outbound method details, and a sanitized audit record.

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
- attachment attempts denied in Phase 1.

## Review Verdict

Do not approve an implementation if tests only call handlers directly and skip inbound validation, access policy, outbound policy, or audit behavior.
