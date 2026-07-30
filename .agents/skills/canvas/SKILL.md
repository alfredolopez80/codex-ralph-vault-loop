---
name: canvas
description: Create visual HTML canvas reports on request for analyses, audits, metrics, timelines, and comparisons.
compatibility: Codex App and CLI. Produces a local, standalone HTML artifact; it does not use Cursor Canvas or .canvas.tsx files.
---

# Canvas Reports

Deliver a user-requested “canvas” as a standalone, self-contained HTML report that opens from Codex. Adapt the presentation intent of Cursor Canvas without relying on Cursor-only `.canvas.tsx` files, the `cursor/canvas` SDK, or Cursor-managed directories.

## When To Use

Use this skill when the user explicitly asks to receive an analysis, audit, investigation, metrics breakdown, timeline, comparison, or other report in a **canvas**, or explicitly invokes `$canvas`.

Do not use this skill merely because information is structured. Skip it for a requested deliverable in another named tool, a code fix, an edit to an existing artifact, short answers, or active debugging unless the user also asks for a canvas report.

## Workflow

1. Establish the evidence before designing the report. Include only verified findings, clearly label inferences, and omit sections without meaningful data. Do not create empty states, placeholder charts, or invented rows.
2. Choose a descriptive kebab-case filename. Unless the user specifies a location or the project has an artifact convention, write one file at `artifacts/<topic>-canvas.html` in the current workspace. Create no helper modules, package manifests, external assets, or network calls.
3. Read the globally installed `visual-explainer` skill for its HTML structure and responsive-layout guidance. Apply this skill's stricter constraints when the two differ: keep the file self-contained, avoid external libraries, and use inline SVG/CSS rather than CDN-loaded charting or diagram packages.
4. Build a responsive semantic HTML document. Give the reader a clear title, a concise executive summary, evidence-backed sections, source/time-range captions, and an explicit uncertainty or limitations section when needed.
5. Use visual hierarchy deliberately: make the main finding prominent, keep supporting evidence compact, and prefer a varied composition over a wall of identical cards. Use real HTML tables for tabular findings and labelled inline SVG charts for quantitative data.
6. Make every chart and table self-explanatory. Name the precise metric, label both axes with units, include a legend for multiple series, and state the source plus time range. Label transformed values such as averages, percentiles, or normalized data.
7. Keep the visual language flat and purposeful. Do not use gradients, emojis as UI, box shadows, rainbow palettes, decorative borders, or oversized headings. Use a restrained accessible palette and respect reduced-motion preferences; do not add decorative animation.
8. Inspect the generated file before delivery. Verify that all claims match the evidence, all labels and links are present, no empty component remains, the HTML is self-contained, and the path is correct.

## Delivery

Report the result in one or two sentences and include a Markdown link using the generated file's absolute path. Explain briefly that the user can open the canvas report beside the task. Do not publish it, open a browser, or send it externally unless the user explicitly requests that action.

## Codex Compatibility Boundary

Do not create `.canvas.tsx` files, import `cursor/canvas`, read Cursor SDK declarations, or write to `~/.cursor/projects/.../canvases/`. Those interfaces belong to Cursor and would not produce a usable Codex artifact. Use a single local HTML file instead.
