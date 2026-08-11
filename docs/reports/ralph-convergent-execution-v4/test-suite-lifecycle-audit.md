# Test Suite Lifecycle Audit

Audit owner: GPT-5.6 SOL Max

Baseline: `78a314b47e6a1017b6d369358fda4c6c28450e06`

Audited candidate: current PR working tree before publication

## Result

| Classification          |        Count | Decision                                                                             |
| ----------------------- | -----------: | ------------------------------------------------------------------------------------ |
| `KEEP`                  |        1,245 | Active v4 contracts, rollback, compatibility, security and existing runtime behavior |
| `REFACTOR`              |  1 test node | Keep, but move to an explicit global/T15 profile lane                                |
| `DELETE`                | 0 test nodes | No pytest node has sufficient evidence for deletion                                  |
| Final pytest collection |        1,246 | Plus 5 subtests                                                                      |

Compared with the exact base, the candidate collects 1,246 pytest nodes versus
1,143: 121 node IDs are added and 18 are removed, for a net increase of 103.
The 18 removals are the retired slop-guard bundle; no active pytest contract
coverage is removed. The added nodes map to explicit plan obligations and stay
in the suite. Legacy tests remain necessary while `off` and `shadow` preserve
rollback to the current runtime.

## Retired bundles

The following files were removed together because they represent one product
capability that was explicitly removed by commit `71792c6` (`Remove slop guard
from Codex hook installs`):

- `scripts/gates/codex_stop_slop_guard.py`
- `tests/unit/test_codex_stop_slop_guard.py` (18 tests)
- the direct slop-guard smoke block in `.codex/tests/run-hook-tests.sh`

The negative assertions in `tests/integration/test_global_install_basic.py`
and `tests/integration/test_hooks_basic.py` remain. They prove that the retired
hook is not copied, registered, or reintroduced. The v4 evidence gate and
finite Stop budget are the current replacement semantics; phrases remain
signal-only and cannot authorize closure.

The standalone Aristotle display shell bundle was also retired after a
separate SOL Max compatibility audit:

- `.codex/hooks/aristotle-analysis-display.sh`
- its syntax-check entry and three direct fixture invocations in
  `.codex/tests/run-hook-tests.sh`

It had no active registration, installer role, or documentation reference;
the active universal classifier and tiered Aristotle tests provide the current
coverage. This removes unreachable shell work only; it removes no pytest
nodes and does not affect the active Aristotle contract.

## Keep, but isolate from ordinary CI

`tests/integration/test_global_model_routing_e2e.py::test_global_dispatcher_routes_the_same_policy_in_a_neutral_workspace`
remains useful evidence for T15/global installation. It reads the real
`~/.codex/hooks.json`, may skip when the installation is absent, and expects a
machine-local global profile. It is not deterministic repository evidence and
should run only in an explicitly provisioned global lane; it is not deleted.

The other 1,245 tests are not deprecated merely because v4 exists. They cover
the active off/shadow rollback path, legacy memory/Recall compatibility,
security boundaries, migrations, hooks, progress persistence, and current
quality gates.

## CI coverage gap

The current GitHub workflow executes the 904 unit tests and redundantly runs
the three regression-guard tests again. The remaining 339 tests (integration,
eval, golden and maintenance) are not deprecated; they simply lack a
continuous CI lane. Removing them would weaken evidence. A future, separately
approved CI change should add explicit lanes for those groups and remove only
the redundant regression rerun.

## Verification

After retiring the bundles:

```text
1246 passed, 5 subtests passed
ALL_HOOK_TESTS_PASS
```

No compatibility aliases were removed. The `anti-rationalization-stop.sh` and
`ralph-stop-quality-gate.sh` aliases remain until an enforce/T15 compatibility
retirement decision is approved.
