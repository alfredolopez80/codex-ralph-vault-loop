---
name: kickoff-doc
description: Turn a shaped project kickoff transcript into a builder-facing reference document organized by system territory.
user-invocable: true
argument-hint: "[kickoff transcript, notes, visuals, mockups, or breadboards]"
---

# Kickoff Document

Use this skill when the user has a kickoff transcript, VTT file, call notes, visuals, mockups, or breadboards and wants a reference document for the person who will build the shaped work.

This is a Codex-safe adaptation of the upstream `kickoff-doc` shaping skill. It has no external command, model, deployment, credential, or network dependency.

## Before You Start

Establish:

1. The primary audience, usually the builder.
2. The source transcript or notes to read.
3. Any supporting inputs: visuals, screenshots, mockups, breadboards, diagrams, or decision notes.

If the source material may contain RED data, keep processing local-only and do not persist raw excerpts outside the target document.

## Organizing Principle

Organize by territory, not timeline.

A kickoff transcript is sequential. People circle back, branch, and mention details out of order. The document should reconstruct the system areas being described, so a builder can look up one area and see the relevant behavior, affordances, decisions, and caveats together.

Do not organize by build sequence. If the team identified implementation slices, those belong in a separate slices or implementation plan document.

## Output Shape

Produce:

```markdown
---
shaping: true
---

# [Project] - Kickoff Reference

## Frame

### Problem

[Why this project, why now, what is broken or missing.]

### Outcome

[The specific outcomes expected.]

## Shape

### [System Area]

[What this area is, what is on screen or in the system, and how it behaves.]

[Inline design decisions and edge cases that belong to this area.]
```

Under `## Shape`, create one `###` section per system area. For each area, capture:

- what it is
- what users see or interact with
- relevant components, affordances, or data
- how it relates to other areas
- design decisions that belong to this area
- called-out edge cases, flags, and temporary placeholders

## Voice

The document records shared understanding from the kickoff.

Do:

- use the actual words and phrases from the call where useful
- synthesize scattered discussion into clear statements
- capture the reasoning people gave for decisions
- mark synthesis when it is not directly stated

Avoid:

- putting new ideas or conclusions in people's mouths
- adding motivational framing not present in the source
- creating a grab-bag design decisions section
- burying area-specific decisions away from the area where they matter

## Review Test

For every claim, identify one of:

- a direct transcript moment
- a clear implication from multiple moments
- an explicit synthesis you are labeling as synthesis

If a claim has none of those, remove it or turn it into an open question.
