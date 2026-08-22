# Hooks

## Current #85 profile: security-only, native execution

Project and global registration contain only
`security_pre_tool_dispatch.py` on `PreToolUse`. It preserves destructive,
RED/egress, package-manager, cloud decision, workspace-boundary, and
symlink-escape controls. Session/prompt/post-tool/subagent/stop continuity and
execution-authority hooks are disabled. Native Codex conversation, compaction,
routing, advisor, and subagent behavior remain platform-owned and are not
vetoed by Ralph.
Context-budget, stale-wakeup, and automation-productivity restrictions are not
part of this security plane. The cloud decision boundary silently allows
proven-safe operations, hard-blocks proven-destructive operations, and emits an
exact one-shot approval instruction for uncertain or non-destructive mutation.

The versioned contract is [`config/security-baseline.toml`](../../config/security-baseline.toml),
and its synthetic gate is `scripts/gates/security-baseline.py`. The lifecycle
components described below remain in the repository as disabled legacy
references for later issues; they are not active in the #85 configuration.

## Legacy lifecycle reference

Hooks provide lifecycle checks for Codex App and Codex CLI. Project hook scripts live in `.codex/hooks`, while `~/.codex/hooks.json` activates them globally.

Events:

- `SessionStart` loads one compact recovery capsule.
- `UserPromptSubmit` composes one safety-first, delta-cached context response.
- `PreToolUse` blocks only the independent security categories implemented by
  `security_pre_tool_dispatch.py`. Routing state and advisor eligibility do not
  participate in the decision.
- `PermissionRequest` remains owned by the native ChatGPT/Codex sandbox; Ralph
  does not add a competing approval process.
- `PostToolUse` runs through the consolidated `post_tool_dispatch.py`. A
  successful non-material local read is a physical no-op in every activation
  mode; material writes, failures, validations, agents, and external calls run
  only their relevant bounded components.
- `SubagentStart` and `SubagentStop` maintain bounded lifecycle/accounting data.
  `SubagentStart` has 16,384 units of context capacity, while the automatic
  advisor packet stays at 4,096 bytes so unused capacity costs no tokens.
- `PreCompact`, `PostCompact`, and `SessionEnd` are intentionally unregistered;
  compact recovery is handled by `SessionStart(source=compact)` and cleanup is
  never a completion gate.
- `Stop` runs through the single `stop_dispatch.py` reducer. It evaluates scoped objective evidence, preserves the file-line and implementation-notes hard gates, and, for an explicit approved progress completion, verifies canonical ownership, provenance, material evidence, validation gates, and current commit/workspace before one terminal store transition. It records route and phrase observations as report-only telemetry, writes a lightweight handoff, and enforces one bounded continuation budget. Heavy memory promotion is marked for later processing and is not run on the critical path.

The single active registration is deliberate. ChatGPT Desktop executes all
matching global, project, and plugin hooks, so keeping one security owner avoids
duplicate blocks. Disabled lifecycle scripts cannot grant or deny execution.

The file-line guard is intentionally blocking for source-like files and intentionally permissive for generated artifacts such as lockfiles, minified assets, maps, and media. When it blocks, Codex must split the file before continuing. The required split style is behavior-preserving and boundary-oriented: tests before and after, domain/use-case/component boundaries, no generic dumping-ground modules, validation/auth/secrets and trust boundaries preserved, sec-context anti-patterns avoided while moving code, and React/Next splits aligned with component-per-file, extracted hooks, direct imports, and lazy loading for heavy UI.

Hooks must degrade safely. Missing files should not crash a session. Hooks must not print secrets and must not save RED content.
For `Stop`, allow/report-only paths must leave stdout empty; only blocking paths emit `{"decision":"block","reason":"..."}`.
For `PostToolUse`, report-only paths must also leave stdout empty. `decision:"warn"` is not a supported Codex hook response and is persisted to local JSONL reports instead.

The shaping ripple hook is warn-only by default. It checks touched Markdown files for `shaping: true` frontmatter and emits a generic checklist to keep related shaping artifacts synchronized. It does not print document contents. Set `RALPH_SHAPING_RIPPLE_STRICT=1` to make the reminder blocking.

The consolidated PostToolUse dispatcher keeps bounded, project-scoped dedupe
and metrics in the Ralph runtime. Its key uses session, turn, and tool-use
identity (including the parent identity of `write_stdin` polls), with a short
TTL and bounded entry count. Corrupt state is quarantined and operational
state failures remain fail-open. Repeating one tool-use identity does not
duplicate candidates, checkpoints, or ledger records.

The consolidated Stop dispatcher keeps state under the project-scoped Ralph
runtime. It emits a block only for current, scoped objective evidence such as a
failed required test, a missing required file, a file-line violation, an
invalid required implementation-notes pair, or a pending task state. Narrative
phrases, missing route markers, stale or foreign state, and pending promotion
are report-only. `stop_hook_active=true` allows immediately. The budget reserves
a continuation atomically before emitting it, permits one ordinary continuation
and one additional continuation only for a new critical evidence fingerprint,
then allows Stop with a local exhaustion warning.

For approved planned work, the PostToolUse checkpoint contains only a bounded
progress reference (`plan_id`, `generation`, `semantic_hash`). The canonical
store owns the objective, phase, decisions, blockers, validation, and next
action narrative. Unplanned tasks continue to use the generic checkpoint shape.
The normal memory wakeup path no longer renders legacy implementation context;
that reader remains available only through its explicit diagnostic/compatibility
flag until migration is complete.

Related phases: [PHASE_07](../migration/checkpoints/PHASE_07.md), [PHASE_16](../migration/checkpoints/PHASE_16.md).
