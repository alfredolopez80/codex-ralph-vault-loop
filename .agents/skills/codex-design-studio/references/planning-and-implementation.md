# Planning And Implementation Reference

Load this when turning the design direction into a concrete plan and scoped implementation.

# Phase 5: Clarifying Questions

After repo and asset analysis, ask only the questions still needed.

Use this format:

```text
I can proceed, but these decisions affect the result.

Critical:
1. ...
2. ...

Useful:
3. ...
4. ...

Optional:
5. ...
6. ...

If you want, I can proceed with these assumptions:
- ...
- ...
```

If the user has already given enough information, do not ask. Instead state assumptions and move to the plan.

If the user says "proceed", "hazlo", "go", or equivalent, proceed with documented assumptions.

# Phase 6: Plan

Before coding or creating final artifacts, produce a plan.

The plan must include:

1. Objective
2. Intended output
3. Target audience
4. Visual direction
5. Information architecture
6. Page/screen/slide structure
7. Component inventory
8. Technical approach
9. Files likely to change
10. Assets needed
11. External references used or intentionally skipped
12. Validation strategy
13. Risks
14. Assumptions
15. Human decisions still needed

For complex work, split into milestones:

```text
Milestone 1: Design-system extraction
Milestone 2: Structural implementation
Milestone 3: Visual polish
Milestone 4: Responsive and accessibility pass
Milestone 5: QA and handoff
```

Do not implement until the plan is clear.

If the user explicitly asked for direct implementation and enough context exists, include a brief plan then implement.

# Phase 7: Implementation

When implementing, follow the existing repo conventions.

## General Implementation Rules

- Use existing components first.
- Use existing tokens first.
- Use existing routing.
- Use existing data-fetching patterns.
- Use existing state management.
- Use existing test approach.
- Use existing formatting conventions.
- Do not introduce a new design system if one already exists.
- Do not introduce a new CSS methodology if the repo already has one.
- Do not add dependencies unless needed and approved.
- Keep components small and composable.
- Keep content editable and easy to replace.
- Use semantic HTML.
- Include accessible labels.
- Include focus-visible states.
- Preserve keyboard navigation.
- Check responsive behavior.

## Frontend Outputs

For web pages, dashboards, app screens, or landing pages:

- Implement desktop, tablet, and mobile behavior.
- Include hover/focus/active states.
- Include loading, error, and empty states when data is involved.
- Avoid layout shift.
- Avoid hard-coded copy if content should come from props/data.
- Use real assets where available.
- Use placeholders only when necessary and label them clearly.
- Ensure CTAs are clear.
- Preserve performance: avoid unnecessary heavy animation or assets.
- Prefer CSS variables or Tailwind theme tokens over one-off colors.
- When useful, A/B test visual variants with screenshots and choose based on readability, hierarchy, usability, brand fit, and implementation cost.

## Asset Generation Rules

Use generated visual assets only when they make the product clearer or more inspectable.

Good uses:

- Product icons
- Game portraits
- Background scenes
- Empty-state illustrations
- Feature thumbnails
- Deck imagery
- Reference imagery for a visual direction

Avoid:

- Decorative filler that does not support the task
- Stock-like imagery when real product screenshots are needed
- Generated assets that obscure product inspection
- Using image generation as a substitute for layout validation

## Full-Stack Outputs

For full-stack projects:

- Identify whether data should be real, mocked, or static.
- Reuse existing API routes or services.
- Do not create migrations without confirmation.
- Do not modify authentication flows without confirmation.
- Do not expose secrets.
- Do not hard-code credentials.
- Keep mocks separate from production logic.
- Document where backend integration is partial.

## Presentation Outputs

For PPTX/deck outputs:

- Keep slides editable where possible.
- Keep text as text.
- Use native shapes/charts where possible.
- Do not rasterize entire slides unless unavoidable.
- Use 16:9 unless source material indicates otherwise.
- Render slide previews for review when possible.
- Check clipping, overflow, margins, font substitution, and alignment.
- Include speaker-flow logic if useful.
- Produce a slide-by-slide summary.

## Prototype Outputs

For prototypes:

- Prioritize credible interaction over fake complexity.
- Make navigation obvious.
- Include enough states to communicate the product.
- Use mock data that reflects real use cases.
- Clearly mark non-functional areas.
- Include a path for productionization.
