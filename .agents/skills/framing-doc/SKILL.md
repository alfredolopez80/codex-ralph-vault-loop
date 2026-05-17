---
name: framing-doc
description: Create an evidence-grounded framing document from transcripts, call notes, stakeholder notes, or conversation records.
user-invocable: true
argument-hint: "[transcript paths, notes, topic area, or frame request]"
---

# Framing Document

Use this skill when the user has transcripts, VTT files, call notes, stakeholder notes, or conversation records and wants a frame that captures what problem is worth solving and why this one should be chosen over alternatives.

This is a Codex-safe adaptation of the upstream `framing-doc` shaping skill. It has no external command, model, deployment, credential, or network dependency.

## Before You Start

Establish:

1. Which source materials to use, including file paths when available.
2. The order to read them in, because conversation order often matters.
3. The topic area, if it is not already clear.

If source material may contain RED data, ask for sanitized input or keep the work local-only. Do not store transcripts in memory or `.local-notes`.

## Output Shape

Produce a frame document with:

```markdown
---
shaping: true
---

# [Topic] - Frame

## Source

### [Speaker] ([Date])

> "Verbatim quote..."

[Brief connective context where needed.]

---

## Pre-work: [Topic] Options Landscape

| Option        | What it does | Who benefits | Signal strength |
| ------------- | ------------ | ------------ | --------------- |
| **A. [Name]** | ...          | ...          | ...             |

**Why A now:** [Evidence-based argument.]

---

## Problem

- [Pain or broken condition, traceable to source]

## Outcome

- [High-level success state, not solution-specific]

---

## Less about

- [What this is not trying to solve]

## More about

- [What kind of solution actually fits]
```

Include `Less about` / `More about` only when the source material shows a meaningful boundary or a likely wrong direction.

## Source Discipline

The Source section is ground truth. Everything else is interpretation.

- Attribute quotes to speakers when possible.
- Keep enough context for each quote to stand alone.
- Use brief connective text only when it helps the reader.
- Keep your own synthesis separate from what people actually said.

After writing each Problem or Outcome bullet, ask: who said this, and where?

- If there is a direct quote, cite it.
- If it is implied by multiple statements, mark it as synthesis and explain briefly.
- If it cannot be traced, remove it.

## Pre-work Discipline

Survey options that surfaced in the conversations. For each option, capture:

- what it does
- who benefits
- how strong the signal is

Make the case for the option to pursue now:

- why it is more urgent or important than others
- why the other options are not first right now

Do not invent a roadmap for the other options. The frame only claims which problem comes first and why.

## Avoid

- Do not shape the solution here. The frame is the why, not the how.
- Do not summarize the conversation chronologically.
- Do not inflate weakly mentioned ideas into options with traction.
- Do not embellish unsupported detail to make a problem sound sharper.
- Do not present your interpretation as somebody else's words.
