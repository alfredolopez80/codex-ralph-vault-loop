---
name: make-requirements-great
description: Review existing requirements or convert raw context into high-quality requirements for PRDs, specs, user stories, acceptance criteria, BRDs, FRDs, requirement catalogues, and stakeholder notes.
user-invocable: true
argument-hint: "[requirements, PRD/spec text, stakeholder notes, or feature idea]"
---

# Make Requirements Great

Use this skill when the user mentions requirements, PRDs, specs, user stories, acceptance criteria, BRDs, FRDs, requirements quality, requirements traceability, requirements catalogues, or shares raw context that should become formal requirements.

This is a Codex-safe adaptation of the upstream `make-requirements-great` skill. It has no external command, model, deployment, credential, or network dependency.

## First Decision

Detect the input mode before doing anything else:

- **Review mode:** the user supplied existing requirements. Audit them against the quality framework, then return rewrites.
- **Author mode:** the user supplied raw context such as notes, transcripts, tickets, pitches, or feature ideas. Extract requirements and write them cleanly from the start.
- **Mixed mode:** extract requirements from loose context, then audit the full set together.

Do not impose a new format unless the user asks. Match the user's existing format where possible. If no format exists, write each requirement as a single clear sentence and add fields only when needed for owner, source, acceptance criteria, or traceability.

## Requirement Level

Always identify the level before auditing. A high-level requirement is not a defective low-level requirement.

- **Business / strategic:** why the work exists; the outcome the organization wants; usually owned by the sponsor.
- **Stakeholder / user:** what a stakeholder needs the system to do for them; expressed at the level of intent.
- **Solution / functional:** how the system behaves; concrete enough for implementation and testing.

If the intended level is ambiguous and the critique depends on that level, ask the user which level they intend. Do not silently default to solution-level.

High-level gaps that are really design decisions should go under **Decisions for decomposition**, not in the defect log. A real defect at high level is a defect at that level: unclear intent, contradiction, missing stakeholder, missing owner, stale scope, or untraceable value.

Default to not decomposing. Split a requirement only when the user asks, the requirement combines multiple intents at its own level, or the user confirms they wanted a lower level of detail.

## The 18 Characteristics

Apply the characteristics as checks, not as vibes. Per-item characteristics apply to individual requirements. Set-level characteristics apply to the catalogue.

### 1. Unambiguous

Can two competent readers independently reach different interpretations? Flag weasel words such as appropriate, suitable, reasonable, user-friendly, intuitive, efficient, fast, robust, scalable, secure, simple, flexible, optimized, high-quality, sufficient, as needed, where applicable, if necessary, may, might, could, and/or.

If a value is undecided, do not invent one. Write the best requirement possible and add an open question.

### 2. Clear And Understandable

The target stakeholders should understand the requirement without a translator. Define domain terms, expand acronyms on first use, and keep sentences parseable in one pass.

### 3. Concise

Remove words that do not change meaning. Keep precision over brevity. The goal is the shortest expression that preserves every constraint.

### 4. Correct

A requirement is correct only when the relevant per-item and set-level characteristics pass and the owner agrees that it represents the actual need.

### 5. Testable

Write the test that would prove the requirement is met. The pass condition must be objective and measurable at the requirement's level.

Business-level testability can be a measurable outcome. Stakeholder-level testability can be an acceptance test that becomes concrete during design. Solution-level testability should be concrete now.

### 6. Implementation-Independent

Scan for named technologies, UI controls, vendors, data structures, screens, and APIs. If the named thing is a design guess, restate the behavior. If it is a real external constraint, label it as such.

### 7. Owned

A named accountable person should confirm correctness, sign off against delivery, and resolve disputes. Do not invent owners. If the owner is missing, flag it.

### 8. Relevant

Every requirement should be in scope and materially advance the business need. Trace it to the problem statement, business case, regulation, stakeholder request, or other source.

### 9. Feasible

Check feasibility against known budget, time, team skills, legal, technology, and operational constraints. If uncertain, mark feasibility pending and list what evidence is needed.

### 10. Unique

Across the catalogue, find duplicates and near-duplicates. Merge true duplicates. Rewrite near-duplicates so the distinction is explicit.

### 11. Cohesive

Each requirement should express one intent at its own level. Split requirements that combine different intents, owners, or tests.

### 12. Consistent

Look for internal contradiction, contradiction between requirements, and terminology drift. Define canonical terms when multiple names refer to the same concept.

### 13. Conformant

Requirements should follow the agreed template, style, fields, and level of detail. If no standard exists, propose one based on the dominant existing format.

### 14. Current

Requirements should have a review date or version signal. Anything older than the latest scope change needs review.

### 15. Modifiable

The catalogue should be easy to change: stable IDs, logical grouping, version history, and cross-references by ID rather than section number.

### 16. Traceable

Each requirement should answer both: where did this come from, and where will it be verified or implemented? Untraceable requirements are candidates for owner review, not automatic deletion.

### 17. Categorized

Classify requirements by type where useful: business, user, functional, non-functional, interface, data, security, performance, reliability, usability, regulatory, or constraint. Thin or missing categories may be findings.

### 18. Complete

Completeness is never fully provable. Show the techniques used: category checklist, CRUD check for key entities, lifecycle check for roles and entities, and reviewer coverage where available.

## Anti-Patterns To Flag

- **Solution-as-requirement:** a design choice is disguised as a need.
- **Compound requirement:** multiple behaviors joined into one statement.
- **Weasel modifier:** subjective or unquantified language hides a decision.
- **Implicit actor:** the requirement omits who does the action.
- **Untestable statement:** no objective pass/fail condition exists.
- **Terminology drift:** the same concept has multiple names.
- **Stealth scope creep:** the requirement assumes out-of-scope work.
- **Orphan:** no source or destination trace exists.

## Output

Return three artifacts unless the user asks for another shape:

1. **Cleaned requirements:** rewrites of the supplied or extracted requirements.
2. **Defect log:** grouped by requirement, listing only failed characteristics; end with set-level findings.
3. **Open questions:** stakeholder decisions needed before correctness can be claimed.

For high-level requirements, add **Decisions for decomposition** when details belong to later design rather than the current requirement level.

## Quick-Pass Mode

If the user asks for a quick check, fast triage, or what jumps out, skip the full log. Surface the highest-impact defects, name the violated characteristic, and give one rewrite per top defect.
