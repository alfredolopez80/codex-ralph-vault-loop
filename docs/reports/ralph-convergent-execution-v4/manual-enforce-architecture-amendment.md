# Manual Enforce Architecture Amendment

**Status:** approved and implemented in `main`

This append-only amendment changes the activation authority for the local
global-hook rollout. The host does not expose an independent model/effort
attestation, so the previous `gpt-5.6-sol/max` runtime-attestation requirement
cannot be honestly materialized.

The active contract is now:

- `enforce` is the only active convergence mode;
- `off` is the explicit rollback mode;
- `shadow` is retired and rejected by the activation parser;
- activation requires a bounded manual-approval artifact under
  `.local-notes/ralph/convergent-manual-activation.toml`;
- the artifact is content-addressed and bound to the plan ID/version/digest,
  policy hash, workspace, branch, full checkout HEAD, approval scope, and
  Codex-main authority;
- the artifact records the SOL/max implementation contract as an approved
  contract, but does not claim that the host independently proved its model
  identity;
- the artifact is local operator state and is never sourced from hook payload
  fields or persisted prompts;
- the global installer, doctor, smoke suite and rollback remain mandatory.

This is a trust-model change, not a provider-cost or model-quality claim.
Credits, provider savings and paired quality remain unmeasured unless their
respective authoritative evidence sources are present.
