---
name: research
description: Perform sanitized research with Z.ai official MCPs, MiniMax MCPs, public web sources, and local synthesis.
---
# Research

## Purpose

Gather external context for Codex work without leaking sensitive content or letting external models make final decisions.

## Routing

For current web information, prefer `zai_web_search` or its `web-search-prime` alias. For a specific URL, prefer `zai_web_reader` or its `web-reader` alias. For public repository research, use `zai_zread` or its `zread` alias. For fast search support, use `minimax_coding_tools.web_search` when available. For local files, use repo tools first and never externalize RED content.

## Source Discipline

Use primary sources where possible. Capture exact URLs for claims that may change. Keep quotes short and necessary. Separate sourced facts from Codex inference. Do not write private research notes into public repo files.

## Output

Research output should state the question answered, sources used, facts found, uncertainty, and implications for the current task.

Codex main decides what to implement or record.
