---
name: ralph-hook-development
description: Develop, test, and benchmark Codex lifecycle hooks while preserving event output contracts, safety gates, and global/project parity.
---

# Ralph hook development

Use this skill when changing `.codex/hooks`, `.codex/hooks.json`, matchers,
dispatchers, lifecycle behavior, hook budgets, or hook benchmarks. It is not
needed for ordinary application code that does not cross a hook boundary.

## Operating procedure

1. Read the relevant event contract in `docs/codex-hooks.md` and the overview in
   `docs/architecture/hooks.md`.
2. Inspect payload fixtures and effective project/global registration before
   editing. A matcher is a dispatch optimization, not the security boundary.
3. Preserve the output contract: allow and report-only paths are silent;
   blocks emit one supported JSON decision with a short safe reason.
4. Keep persistence atomic and locked. Local persistence errors follow the
   existing fail-open contract; destructive and egress decisions stay explicit.
5. Update project and installer sources together. Do not install global
   configuration during repository tests.

## References

- Event contracts: `docs/codex-hooks.md`.
- Lifecycle overview: `docs/architecture/hooks.md`.
- Benchmark and comparison: `scripts/evals/hook_runtime_cost_benchmark.py` and
  `scripts/evals/compare_hook_benchmarks.py`.

## Required validation

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_hook_config_lockstep.py tests/integration/test_hooks_basic.py tests/integration/test_hook_lifecycle_e2e.py -q
bash .codex/tests/run-hook-tests.sh
python3 scripts/setup/smoke-global-hooks.py
bash scripts/setup/doctor-global.sh
RALPH_HOOK_COST_ITERATIONS=5 python3 scripts/evals/hook_runtime_cost_benchmark.py --json-out /tmp/ralph-hook-benchmark.json --markdown-out /tmp/ralph-hook-benchmark.md
```

For an installer check, set `HOME` to a fresh temporary directory. Never
mutate the user's global configuration as part of a repository test.
