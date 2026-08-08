---
name: ralph-kubernetes-safety
description: Validate Kubernetes, Minikube, Docker, profile ownership, contexts, and branch-safe port forwarding before runtime work.
---

# Ralph Kubernetes safety

Use this skill for `kubectl`, Minikube, Docker or Compose, cluster deployment,
profile inspection, port-forwarding, or local runtime gates. Do not load it for
ordinary repository tests.

## Operating procedure

1. Prove the active worktree, branch, HEAD, base, profile, context, and running
   processes before reusing a cluster. A healthy profile is not proof of
   ownership.
2. Pass an explicit `--context` to every `kubectl` invocation. Use the primary
   checkout's branch-profile helper when it exists; use generated branch-owned
   random ports instead of fixed machine-global ports.
3. Run Docker and Minikube interactions outside the native Codex sandbox.
   Prefer the repository's reviewed operation and authorization scripts; do
   not invent a direct destructive command.
4. Keep credentials and restricted runtime data local. Record only profile,
   context, URLs, hashes, and bounded diagnostics in reports.
5. Recheck ownership and dirty state after the gate. Invalidate evidence from
   a profile that belonged to another branch or process.

## Required checks

```bash
ps -ef | rg "<profile>|pre-gate-sync|pf-all-stack|port-forward"
kubectl --context <owned-context> config current-context
kubectl --context <owned-context> get pods
```

Use the project-specific `make -f .../branch.mk branch-profile-info` and
`scripts/minikube/pre-gate-sync.sh` when applicable. Never use a fixed shared
port merely because a cluster reports healthy.

## References

- Runtime policy: `AGENTS.md` and `docs/codex-productivity-patterns.md`.
- Reviewed operations: `scripts/security/` and `scripts/operations/`.
- Hook command gate: `docs/codex-hooks.md`.
