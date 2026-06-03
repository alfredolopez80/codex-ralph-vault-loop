# Handler Contract

The target app should define a framework-neutral event contract before handlers run. Webhook and polling paths should both emit this same internal event shape.

## Event Shape

Recommended fields:

- `eventId`: stable app event id.
- `source`: `webhook` or `polling`.
- `updateId`: Telegram update id.
- `chat`: minimal chat id, type, and allowlist status.
- `actor`: minimal user id and allowlist status.
- `kind`: command, text, callback, edited message, or unsupported.
- `text`: sanitized text when relevant.
- `command`: parsed command name and safe arguments when relevant.
- `callback`: parsed callback name and scoped payload when relevant.
- `policy`: access decision and reason.

Do not make raw Telegram JSON the handler contract. Keep raw payload access behind explicit debug tooling and never log it by default.

## Handler Rules

- Access policy runs before the handler.
- Handlers are registered by explicit command or event kind.
- Unknown commands produce a safe generic response or no response.
- Handler errors are converted to sanitized app errors.
- Handler output goes through outbound policy before sending.

## Group Rules

Groups are disabled by default. If a target app enables groups, the handler context must include chat allowlist status, mention or reply match, actor authorization, and per-chat rate state.

## Admin Mutations

Telegram input must not mutate admin policy unless the target app implements a deliberate admin flow with authorization, confirmation, audit, and negative tests.
