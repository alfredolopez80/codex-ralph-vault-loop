# Design-System Extraction Reference

Load this when the task needs persistent design-system dossiers, tokens, component notes, or style documentation.

# Phase 4: Design-System Extraction

If the task is open-ended or brand-driven, create a design-system dossier before implementation.

Do not create these files if the user only wants a quick minor UI fix.

If creating persistent repo artifacts, prefer:

```text
docs/design-studio/
  STYLE_AUDIT.md
  REFERENCE_RESEARCH.md
  DESIGN_SYSTEM.md
  TOKENS.json
  COMPONENTS.md
  ART_BIBLE.md
  WEB_STYLE.md
  PRESENTATION_STYLE.md
  IMPLEMENTATION_PLAN.md
  QA_CHECKLIST.md
  HANDOFF.md
```

If the repo has a different docs/design convention, use that instead.

If the user does not want persistent docs, produce the same information in the conversation and avoid creating files.

## STYLE_AUDIT.md

Must include:

- Source assets reviewed
- Brand personality
- Color analysis
- Typography analysis
- Layout analysis
- Component analysis
- Presentation analysis, if relevant
- Accessibility observations
- What to preserve
- What to avoid
- Unknowns
- Assumptions

## REFERENCE_RESEARCH.md

Create this when external design libraries or public product references materially influence the direction.

Must include:

- User copy or product signals analyzed
- Queries used
- Sources reviewed
- Shortlisted references
- Why each reference was relevant
- Portable rules extracted
- Rules rejected
- Licensing or brand-copying risks
- Mapping to current repo tokens/components
- Remaining uncertainty

## DESIGN_SYSTEM.md

Must include:

- Design principles
- Visual direction
- Color roles
- Typography system
- Spacing system
- Layout/grid rules
- Radius and shadows
- Component rules
- Responsive behavior
- Accessibility rules
- Content tone
- Examples of correct usage
- Examples of incorrect usage

## ART_BIBLE.md

Create this when the work establishes or changes the project's visual language across multiple screens, assets, or deliverables.

Must include:

- Screenshot sources reviewed
- Visual principles extracted from the implemented result
- Palette rules
- Typography rules
- Layout rules
- Component and state rules
- Imagery and asset rules
- Motion and interaction rules
- Responsive rules
- Do / do-not examples
- Open questions for future design work

## TOKENS.json

Use this shape when useful:

```json
{
  "colors": {
    "background": "",
    "surface": "",
    "surfaceElevated": "",
    "border": "",
    "text": "",
    "textMuted": "",
    "primary": "",
    "primaryContrast": "",
    "secondary": "",
    "accent": "",
    "danger": "",
    "success": "",
    "warning": ""
  },
  "typography": {
    "fontSans": "",
    "fontSerif": "",
    "fontMono": "",
    "scale": {
      "xs": "",
      "sm": "",
      "base": "",
      "lg": "",
      "xl": "",
      "2xl": "",
      "3xl": "",
      "4xl": "",
      "5xl": ""
    },
    "lineHeight": {},
    "letterSpacing": {}
  },
  "spacing": {
    "1": "",
    "2": "",
    "3": "",
    "4": "",
    "6": "",
    "8": "",
    "12": "",
    "16": "",
    "24": ""
  },
  "radius": {
    "sm": "",
    "md": "",
    "lg": "",
    "xl": "",
    "full": ""
  },
  "shadow": {
    "sm": "",
    "md": "",
    "lg": ""
  },
  "breakpoints": {
    "sm": "",
    "md": "",
    "lg": "",
    "xl": ""
  }
}
```

## COMPONENTS.md

Must include:

- Existing components found
- Components to reuse
- Components to create
- Component props where useful
- States required
- Responsive behavior
- Accessibility notes

## WEB_STYLE.md

Must include:

- Page rhythm
- Section patterns
- Hero patterns
- Navigation rules
- CTA rules
- Form rules
- Dashboard rules
- Data visualization rules
- Mobile behavior

## PRESENTATION_STYLE.md

Must include:

- Aspect ratio
- Cover slide style
- Section divider style
- Content slide style
- Chart style
- Diagram style
- CTA slide style
- Typography
- Spacing
- Footer/header rules
- Export requirements
- Editable-slide requirements
