# Security Policy

## Supported Versions

This repository is pre-1.0. Security fixes are applied to the default branch.
Older snapshots are unsupported unless a maintainer tags a release and states
support for it.

## Reporting A Vulnerability

Please report vulnerabilities through GitHub Security Advisories for this
repository. If advisories are unavailable, open a minimal issue that describes
the affected component and impact using sanitized evidence only.

Useful reports include:

- affected file or component;
- reproduction steps using sanitized inputs;
- expected and actual behavior;
- impact assessment;
- suggested mitigation, if known.

Do not post live access material, vault data, raw local memory content, or
unsanitized logs in public issues or pull requests.

## Security Boundaries

Codex remains the orchestrator. External models and remote MCP tools are
advisors only, and RED content must stay local. This repo should not contain
private vault data, personal local paths, raw transcripts, or unsanitized logs.

Before publishing or merging security-sensitive changes, run:

```bash
gitleaks detect --no-banner --redact
semgrep --config .semgrep.yml .
python3 scripts/gates/run-security.py --mode standard
```
