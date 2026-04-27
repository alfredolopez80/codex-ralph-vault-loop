# Architecture Diagrams

These diagrams document the Codex Ralph Vault Loop setup as it runs in Codex CLI and Codex App.

They were generated using the global `fireworks-tech-graph` skill style guidance:

- Template family: `architecture`, `agent-architecture`, and `data-flow`.
- Visual style: OpenAI-style clean technical diagrams.
- Source format: editable JSON beside rendered SVG and PNG.

Files:

- `codex-ralph-architecture.json`, `.svg`, `.png`: full system architecture.
- `routing-security-flow.json`, `.svg`, `.png`: sensitivity, cost routing, MCP, and gate flow.
- `memory-eval-lifecycle.json`, `.svg`, `.png`: wakeup, runtime memory, evals, vault, and handoff lifecycle.

Regenerate PNGs after SVG edits:

```bash
rsvg-convert -w 1920 docs/architecture/diagrams/codex-ralph-architecture.svg -o docs/architecture/diagrams/codex-ralph-architecture.png
rsvg-convert -w 1920 docs/architecture/diagrams/routing-security-flow.svg -o docs/architecture/diagrams/routing-security-flow.png
rsvg-convert -w 1920 docs/architecture/diagrams/memory-eval-lifecycle.svg -o docs/architecture/diagrams/memory-eval-lifecycle.png
```
