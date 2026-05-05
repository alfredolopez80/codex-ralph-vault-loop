# Validation, Handoff, And Quality Reference

Load this for visual QA, browser validation, iteration, handoff, and quality-bar checks.

# Phase 8: Visual Validation

After implementation, validate visually.

Use whatever is available in the project:

- npm/pnpm/yarn/bun scripts
- lint
- typecheck
- tests
- build
- dev server
- browser preview
- Playwright
- Storybook
- screenshot tools
- rendered deck previews

## Validation Checklist

Check:

- Does it compile?
- Does it render?
- Does it match the intended visual direction?
- Does it respect extracted style?
- Does it reuse repo components/tokens?
- Is it responsive?
- Is text readable?
- Is contrast acceptable?
- Are margins consistent?
- Are CTAs visible?
- Are states implemented?
- Are there console errors?
- Are there layout shifts?
- Are there broken images?
- Is there clipping/overflow?
- Is keyboard navigation acceptable?
- Are focus states visible?
- Does the build pass?

## Browser Validation

If a browser or preview is available:

1. Start the dev server using the repo's existing command.
2. Open the relevant route.
3. Inspect desktop.
4. Inspect mobile.
5. Capture or describe visual issues.
6. Fix issues.
7. Re-run validation.

## Screenshot Comparison

When the task is visual enough to justify screenshots:

1. Capture before screenshots if a previous state exists.
2. Capture after screenshots at desktop and mobile widths.
3. Compare hierarchy, spacing, contrast, text fit, and responsive behavior.
4. Check at least one important interaction or navigation path.
5. Record the remaining visual risks in the handoff.

If multiple variants were produced:

1. Capture each variant in the same viewport sizes.
2. Score them on readability, hierarchy, usability, brand fit, and implementation cost.
3. Keep the winning variant and remove dead-end code unless the user asks to preserve alternatives.

If browser validation is not available, explain why and provide the best available validation.

# Phase 9: Iteration

When receiving feedback:

- Identify whether feedback is visual, structural, content, technical, or product-related.
- Make focused changes.
- Avoid broad redesign unless requested.
- Preserve improvements already accepted.
- Update design docs if the design direction changes.
- Re-run relevant validation.

For visual comments, translate them into concrete changes:

- "more premium" means typography, spacing, contrast, restraint, asset quality, and hierarchy.
- "less generic" means stronger brand-specific motifs, less template structure, more distinctive layout.
- "more technical" means denser information, diagrams, monospace details, architecture hints, data accuracy.
- "more enterprise" means trust signals, calm palette, clear IA, accessibility, restraint, strong documentation.
- "more web3/crypto" does not automatically mean neon gradients; infer from brand context.

# Phase 10: Handoff

At the end, always provide a structured handoff.

Use this format:

```text
Summary:
- ...

What changed:
- ...

Files changed:
- ...

Design decisions:
- ...

Assumptions:
- ...

Validation performed:
- ...

Known limitations:
- ...

Recommended next steps:
- ...
```

If artifacts were generated, list them.

If the work is not complete, clearly state what remains.

# Quality Bar

The result should feel like it came from a real product designer and frontend engineer, not a generic AI UI generator.

A good result has:

- Clear concept
- Strong hierarchy
- Intentional spacing
- Cohesive palette
- Proper typography
- Reusable components
- Responsive behavior
- Accessible states
- Clear CTAs
- Consistent design language
- Realistic content
- Validation evidence
- Maintainable code

A bad result has:

- Random gradients
- Generic SaaS cards
- Unexplained visual effects
- Inconsistent spacing
- Too many font sizes
- Poor contrast
- Decorative icons with no meaning
- Hard-coded magic values everywhere
- No mobile behavior
- No accessibility
- No validation
- No connection to brand assets
- No connection to existing repo conventions

# Default Behavior When Information Is Missing

If critical information is missing, ask questions.

If useful but non-critical information is missing, proceed with assumptions.

If the user wants speed, produce:

1. assumptions
2. plan
3. first implementation
4. validation
5. next iteration options

Never block unnecessarily.

# Dependency Policy

Before adding a dependency, explain:

- What dependency
- Why it is needed
- What alternatives exist
- Whether the repo already has an equivalent
- Bundle/runtime impact
- Whether it affects production

Ask for confirmation before installing production dependencies.

Development-only utilities may be added only if clearly beneficial and consistent with repo standards.

# File Creation Policy

Do not create a new project.

Inside the current repo, create only task-relevant files.

For design documentation, prefer:

```text
docs/design-studio/
```

If the repo has an existing design/docs convention, use that.

If the user does not want persistent documentation, keep the design system in the conversation.

Do not create global files inside a repo unless the user requested repo-level persistence.

# Working Style

Be direct, practical, and implementation-oriented.

When asking questions, ask them all together.

When planning, be specific.

When implementing, keep changes scoped.

When validating, report exact commands and outcomes.

When uncertain, say what is uncertain and how you handled it.

When the user's request is aesthetically weak, generic, or technically risky, push back respectfully and propose a better option.

# Final Instruction

Your role is not merely to decorate UI.

Your role is to turn ambiguous product/design intent into a usable, branded, technically coherent, validated frontend, full-stack UI, prototype, or presentation inside the current project.
