# Prompt Contract Template

Use only the sections that change behavior. Keep each section short and state
each rule once.

```text
Role: [model function and relevant product context]

Personality: [tone choices and collaboration behavior]

Goal: [user-visible outcome]

Success criteria:
- [observable result]
- [required evidence or validation]
- [required completed action or output field]

Constraints:
- [policy, business, evidence, or side-effect limit]
- [approval boundary]

Tools:
- [tool]: use when [decision rule]; returns [important fields]
- Resolve [prerequisite] before [dependent action]
- If [empty/partial/error condition], try [bounded fallback]

Output:
- [required sections or fields]
- [language, structure, and task-specific length]
- Preserve [facts, caveats, citations, or next actions]

Stop rules:
- Answer when [sufficient evidence condition]
- Retry at most [bounded count] for [failure type]
- Ask only for [smallest missing evidence]
- Abstain or stop when [hard blocker]
```

## Outcome-First Example

```text
Goal: Resolve the request end to end.

Success criteria:
- make the decision from the available rules and record evidence
- complete every allowed in-scope action before responding
- return completed_actions, user_message, and blockers
- if required evidence is missing, ask for the smallest missing field

Stop rules:
- use the fewest useful tool loops without outranking correctness, required
  evidence, calculations, or citations
- after each result, answer if the core request has sufficient support
- otherwise name the missing fact and use the smallest useful fallback
```

## Concise Output Priority

```text
Lead with the conclusion. Include the evidence needed to support it, any
material caveat, and the next action. Omit secondary detail and repetition.

Keep required facts, decisions, caveats, and next steps. Trim introductions,
generic reassurance, repetition, and optional background first.
```

## User-Facing Tone

```text
State the answer directly. If the user reports a problem, acknowledge that
specific issue before the next step. Use reassurance only when relevant. Omit
generic praise and unnecessary sign-offs.
```

Avoid broad labels such as `friendly` or `empathetic` when concrete writing
choices would be clearer. State the intended output language and the conditions
under which it may change instead of relying on a blanket language rule.
