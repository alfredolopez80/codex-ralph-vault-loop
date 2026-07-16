# Tool Calling, Grounding, And State

## Tool Descriptions

A useful description states what the tool does, when to use and not use it,
prerequisite discovery or validation, important return fields, and partial,
empty, timeout, and error behavior.

Expose only tools relevant to the current task. Parallelize independent reads;
keep calls sequential when one result changes the next decision.

## Programmatic Tool Calling

Use Programmatic Tool Calling (PTC) for a bounded stage where code reduces many
structured results to a smaller deterministic schema.

Good fits include filtering, joining, sorting, ranking, deduplication,
aggregation, batching similar reads, repeated deterministic validation, and
reducing large structured results to compact evidence.

Prefer direct calls when one call is sufficient, outputs are already small,
semantic judgment is required between calls, an action requires approval,
citations or native artifacts must be preserved, or each result determines the
next action.

Define the bounded stage, eligible read-only tools, exact output schema, retry
limit, stop condition, and handoff to direct judgment. Do not switch routes or
repeat completed work after the handoff.

```text
Use Programmatic Tool Calling only for the bounded record-reduction stage.
Call only the documented read-only tools. Filter and deduplicate intermediate
results, then emit the required compact schema with evidence fields. Retry
transient failures at most twice. Use direct calls for approval, semantic
judgment, citations, and final validation.
```

Test both `program_output` and the final assistant `message`; the program may
return correct records while the message omits a required field or caveat.

## Grounding And Retrieval Budgets

For ordinary grounded Q&A:

1. Start with one broad search using short, discriminative keywords.
2. Answer if the top results support the core request.
3. Retrieve again only when a required fact, owner, date, ID, source, specific
   artifact, exhaustive comparison, or material claim remains unsupported.
4. Do not search only to improve phrasing, add optional examples, or support
   nonessential detail.

For research and synthesis, cite only retrieved sources, attach citations to
the claims they support, label inference separately, surface conflicts, narrow
the answer when evidence is missing, and do not turn absence of evidence into a
factual `no`.

For creative drafting, distinguish sourced facts from creative wording. Do not
invent names, metrics, dates, roadmap status, outcomes, or capabilities merely
to make the draft stronger.

## Long-Running Work

Before tools for a multi-step task, give a one- or two-sentence preamble naming
the first step. Update only at major phase changes or when a finding changes the
plan. Each update should state one concrete outcome and the next step.

Preserve assistant phase values when replaying history. With
`previous_response_id`, prior assistant state is preserved automatically. With
manual replay, keep original phase values unchanged.

Compact after major milestones, not every turn. Keep the prompt functionally
consistent and treat compacted items as opaque state. Reuse persisted reasoning
only while the objective, assumptions, and priorities remain stable.

Keep reusable prompt prefixes stable for caching. Add explicit cache breakpoints
only when representative measurements show a benefit.
