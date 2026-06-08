# Report-Only Automation Scout

Use this reference when the task requires future attention instead of immediate
inline work.

## Action Policy

Propose first. Create, update, or delete an automation only after explicit user
approval and only through the available automation tooling. Keep automations
report-only by default unless the user approves a specific write action.

For cron-shaped local jobs, draft the command and hand it over. Do not install
or schedule local jobs silently.

## Recognition Signals

- The user asks to check, remind, monitor, revisit, or follow up later.
- Work depends on external state such as CI, deploys, queues, releases, inboxes,
  or issue trackers.
- The same report would be useful daily, weekly, or after a known event.
- A "babysitting" loop would otherwise keep this thread open while nothing can
  be done locally.

## Ralph Fit

Prefer:

- Thread wakeups when the existing conversation context matters.
- Standalone project automations for recurring reports that should not depend
  on the current thread.
- `codex exec` under an approved scheduler when the task is scriptable and needs
  a shell exit code.

Include relevant skills in the drafted prompt, such as `$autoreview`,
`$handoff`, `$ralph-central-memory`, or `$ralph-opportunity-scout`, when that
would make the run safer and more repeatable.

## Stay Inline When

- The waiting task will finish during this session.
- Only two or three immediate checks are needed.
- A native `/goal` is a better fit because the desired behavior is "continue
  until condition X is true" rather than "run on cadence Y."
- The job would need sensitive context that should not be persisted or sent
  anywhere.

## Proposal Template

```text
Opportunity: This is recurring or deferred work.
Best Ralph path: <thread automation | project automation | codex exec cron>.
Why now: <state being watched, cadence, or deferred obligation>.
Approval needed: Yes, before creating or scheduling anything.
Inline fallback: I will do the current check once here and leave no automation.
```
