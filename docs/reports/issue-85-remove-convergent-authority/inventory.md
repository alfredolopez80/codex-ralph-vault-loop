# Issue #85 authority-removal inventory

Source of truth: issues #83 and #85. Previous checkpoint: `PHASE_22` PASS.

## Classification

| Class               | Paths / behavior                                                                                                                                                                                                                  | Decision                                                                                          |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `security-preserve` | `.codex/hooks/security_pre_tool_dispatch.py`, `pre_tool_guard.py`, `shared/security_boundary.py`, cloud/SFW helpers, `config/security-baseline.toml`, security fixtures and graph checks                                          | Keep unchanged as the only active blocking plane.                                                 |
| `remove`            | Frozen authority/store/reducer/contracts; activation, policy, lease, decision-packet, prompt-boundary, final-audit and attestation modules/config; combined PreTool dispatcher; routing/advisor PreTool guards; structural canary | Delete after severing dispatcher imports.                                                         |
| `rewrite`           | Prompt/PostTool/Stop compatibility dispatchers, global role allowlist, graph classifications, installer/audit/smoke maps, root instructions, routing and hook docs                                                                | Remove execution-permission dependencies while leaving later lifecycle work to its mapped issues. |
| `derived`           | v4 architecture document, diagrams, phase reports and adjudication artifacts                                                                                                                                                      | Delete; they described the retired runtime covenant.                                              |
| `test-only`         | State-machine, authority, activation, lease, attestation, canary, prompt-boundary and veto-specific unit/integration suites                                                                                                       | Delete; retain security baseline, lockstep, graph and ordinary advisory-policy tests.             |

## Independence proof

- Project/global registration contains only `security_pre_tool_dispatch` on `PreToolUse`.
- The security dispatcher depends on `pre_tool_guard` and `shared/security_boundary`, not on any removed authority, routing-veto, or advisor-veto module.
- The versioned `SECURITY_BASELINE` remains the unchanged v3 contract, including its negative assertion that the retired plane is disabled.
- Routing and advisors remain optional recommendations; neither is an allow/block owner.
- An active-source import search returns no reference to a deleted authority or veto module.
- The installed global hook tree contains none of the retired dispatcher, routing-veto, advisor-veto, activation, lease, policy, or attestation paths.

## Certification

- `SECURITY_BASELINE` v3: 18/18 fixtures pass (8 blocks, 1 native approval, 9 allows).
- Full unit suite: 828 tests plus 5 subtests pass.
- Hook/global integration: 120 pass, 1 skip; dedicated security integration: 5 pass.
- Minimal gate: 4/4 pass; effective graph reports `security-only` and one blocking owner.
- Global smoke, doctor (`warnings=0`), and pre-global audit pass after installation.
- Critical project/global hook hashes match.

## Removal boundary

This phase does not activate continuity, prompt, PostTool, subagent-lifecycle, or Stop hooks and does not advance to #78. Disabled compatibility handlers that do not implement the retired authority remain for their later mapped cleanup issues.
