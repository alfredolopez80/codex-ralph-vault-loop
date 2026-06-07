# Architecture Diagrams

These diagrams document the Codex Ralph Vault Loop setup as it runs in Codex CLI and Codex App.

They were generated using the global `fireworks-tech-graph` skill style guidance:

- Template family: `architecture`, `agent-architecture`, `data-flow`, and `flowchart`.
- Visual style: OpenAI-style clean technical diagrams.
- Source format: editable JSON beside rendered SVG and PNG.

Files:

- `codex-ralph-architecture.json`, `.svg`, `.png`: full system architecture.
- `routing-security-flow.json`, `.svg`, `.png`: sensitivity, cost routing, MCP, and gate flow.
- `memory-eval-lifecycle.json`, `.svg`, `.png`: wakeup, runtime memory, evals, vault, and handoff lifecycle.
- `memory-tree-v2-model.json`, `.svg`, `.png`: feature-flagged Memory Tree v2 recall, selection, progressive retrieval, trace, and legacy fallback model.
- `ralph-memory-refinement.json`, `.svg`, `.png`: readable graduation flow for hook capture, quarantine, Aristotelian review, curated MiVault memory, and recall-default use.
- `ralph-memory-worktree-architecture.json`, `.svg`, `.png`: worktree-aware split between stable hook code, active project identity, project runtime memory, MiVault, and recall.
- `ralph-memory-graduation-recall-flow.json`, `.svg`, `.png`: quarantine, source-project checks, Aristotelian review, auto/ask/skip decisions, and recall-default behavior.

Regenerate SVG and PNG for the Ralph memory refinement flow:

```bash
python3 ~/.codex/skills/fireworks-tech-graph/scripts/generate-from-template.py flowchart docs/architecture/diagrams/ralph-memory-refinement.svg "$(python3 -c 'import json; print(json.dumps(json.load(open("docs/architecture/diagrams/ralph-memory-refinement.json", encoding="utf-8"))))')"
bash ~/.codex/skills/fireworks-tech-graph/scripts/validate-svg.sh docs/architecture/diagrams/ralph-memory-refinement.svg
rsvg-convert -w 1920 docs/architecture/diagrams/ralph-memory-refinement.svg -o docs/architecture/diagrams/ralph-memory-refinement.png
```

Regenerate the worktree-aware memory diagrams:

```bash
python3 ~/.codex/skills/fireworks-tech-graph/scripts/generate-from-template.py memory docs/architecture/diagrams/ralph-memory-worktree-architecture.svg "$(python3 -c 'import json; print(json.dumps(json.load(open("docs/architecture/diagrams/ralph-memory-worktree-architecture.json", encoding="utf-8"))))')"
bash ~/.codex/skills/fireworks-tech-graph/scripts/validate-svg.sh docs/architecture/diagrams/ralph-memory-worktree-architecture.svg
rsvg-convert -w 1920 docs/architecture/diagrams/ralph-memory-worktree-architecture.svg -o docs/architecture/diagrams/ralph-memory-worktree-architecture.png

python3 ~/.codex/skills/fireworks-tech-graph/scripts/generate-from-template.py flowchart docs/architecture/diagrams/ralph-memory-graduation-recall-flow.svg "$(python3 -c 'import json; print(json.dumps(json.load(open("docs/architecture/diagrams/ralph-memory-graduation-recall-flow.json", encoding="utf-8"))))')"
bash ~/.codex/skills/fireworks-tech-graph/scripts/validate-svg.sh docs/architecture/diagrams/ralph-memory-graduation-recall-flow.svg
rsvg-convert -w 1920 docs/architecture/diagrams/ralph-memory-graduation-recall-flow.svg -o docs/architecture/diagrams/ralph-memory-graduation-recall-flow.png
```

Regenerate PNGs after SVG-only edits:

```bash
rsvg-convert -w 1920 docs/architecture/diagrams/codex-ralph-architecture.svg -o docs/architecture/diagrams/codex-ralph-architecture.png
rsvg-convert -w 1920 docs/architecture/diagrams/routing-security-flow.svg -o docs/architecture/diagrams/routing-security-flow.png
rsvg-convert -w 1920 docs/architecture/diagrams/memory-eval-lifecycle.svg -o docs/architecture/diagrams/memory-eval-lifecycle.png
rsvg-convert -w 1920 docs/architecture/diagrams/memory-tree-v2-model.svg -o docs/architecture/diagrams/memory-tree-v2-model.png
rsvg-convert -w 1920 docs/architecture/diagrams/ralph-memory-refinement.svg -o docs/architecture/diagrams/ralph-memory-refinement.png
rsvg-convert -w 1920 docs/architecture/diagrams/ralph-memory-worktree-architecture.svg -o docs/architecture/diagrams/ralph-memory-worktree-architecture.png
rsvg-convert -w 1920 docs/architecture/diagrams/ralph-memory-graduation-recall-flow.svg -o docs/architecture/diagrams/ralph-memory-graduation-recall-flow.png
```
