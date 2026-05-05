# Intake And Reconnaissance Reference

Load this when the task needs design intake, repo scanning, or project diagnosis details.

# Phase 1: Intake

Before implementation, determine the user's real objective.

Ask a compact intake questionnaire if the user has not already provided the answers.

Do not ask more than 12 questions at once.

Group questions by category.

Mark questions as:

- Critical
- Useful
- Optional

If enough information exists, do not over-question. State assumptions and proceed to planning.

## Intake Questionnaire

Ask some or all of these depending on context:

### Goal

1. What are we building?
   - landing page
   - product page
   - dashboard
   - app screen
   - onboarding flow
   - pitch deck
   - presentation
   - one-pager
   - microsite
   - prototype
   - full feature

2. What is the business or product objective?
   - acquire leads
   - explain product
   - sell
   - onboard users
   - demo a feature
   - raise funding
   - internal tool
   - support sales
   - improve UX

3. Who is the target audience?
   - developers
   - enterprise buyers
   - consumers
   - investors
   - internal operators
   - technical users
   - non-technical users

### Output

4. What output should be delivered?
   - implemented code
   - static prototype
   - interactive prototype
   - responsive web page
   - deck/PPTX
   - PDF
   - HTML microsite
   - Figma-aligned implementation
   - design system documentation

5. Should this be production-ready or a concept prototype?

6. Should the output integrate with real backend/data, mocked data, or placeholder content?

### Brand And Style

7. Are there brand assets or references?
   - PDFs
   - PPTX decks
   - screenshots
   - images
   - logos
   - website URLs
   - Figma links
   - existing product screens
   - brand guidelines

8. What visual direction should it follow?
   - premium
   - enterprise
   - developer-first
   - editorial
   - playful
   - minimalist
   - technical
   - futuristic
   - institutional
   - brutalist
   - luxury
   - crypto/web3
   - fintech
   - telecom
   - cybersecurity

9. What should be avoided visually?

### Content

10. Is final copy available, or should draft copy be generated?

11. Are there required sections/slides/screens?

12. Are there legal, compliance, localization, accessibility, or data constraints?

### Technical Constraints

13. Should we preserve the current stack exactly?

14. Are there existing components or design tokens that must be used?

15. Are there build/test/lint commands that must pass?

16. Are new dependencies allowed?

17. Should the work happen in the current branch, a new branch, or a worktree?

# Phase 2: Repository Reconnaissance

Before designing or implementing, inspect the repository.

Perform a lightweight scan first.

Recommended checks:

- Current directory
- Git status
- Package manager
- Framework
- Routing structure
- Styling system
- Component library
- Existing design tokens
- Existing assets
- Test/lint/build scripts
- Existing documentation
- Existing AGENTS.md or project guidance

## Look For These Files And Directories

Common project files:

- package.json
- pnpm-lock.yaml
- yarn.lock
- package-lock.json
- bun.lockb
- tsconfig.json
- vite.config.\*
- next.config.\*
- nuxt.config.\*
- remix.config.\*
- astro.config.\*
- svelte.config.\*
- angular.json
- tailwind.config.\*
- postcss.config.\*
- eslint.config.\*
- biome.json
- .prettierrc
- AGENTS.md
- README.md

Frontend directories:

- src/
- app/
- pages/
- components/
- ui/
- styles/
- public/
- assets/
- lib/
- hooks/
- routes/
- layouts/
- design/
- docs/
- stories/
- .storybook/

Full-stack directories:

- api/
- server/
- backend/
- services/
- prisma/
- db/
- migrations/
- controllers/
- routes/
- models/
- serializers/
- views/
- templates/

Design-system clues:

- CSS variables
- Tailwind theme extension
- design tokens
- shadcn/ui
- Radix
- Material UI
- Chakra
- Mantine
- Ant Design
- Bootstrap
- Storybook
- Figma references
- theme files
- typography files
- color files
- component primitives

## Repository Diagnosis Output

After scanning, report:

```text
Project type:
Framework:
Language:
Package manager:
Styling system:
Component system:
Routing:
Assets:
Design tokens:
Build command:
Lint command:
Test command:
Preview/dev command:
Design risks:
Implementation constraints:
```

If the repo structure is unclear, ask the user before implementing.
