from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "scripts" / "evals" / "hook_runtime_cost_benchmark.py"


def test_hook_runtime_cost_benchmark_emits_metrics_contract(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["RALPH_HOOK_COST_ITERATIONS"] = "1"
    env["RALPH_HOME"] = str(tmp_path / "ralph")
    env["CODEX_MEMORY_HOME"] = str(tmp_path / "codex-memory-empty")
    env["VAULT_DIR"] = str(tmp_path / "vault-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""

    result = subprocess.run(
        [sys.executable, str(BENCHMARK)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    json_text, metric_text = result.stdout.split("\nMETRIC ", 1)
    report = json.loads(json_text)
    assert report["iterations"] == 1
    assert {case["payload"] for case in report["cases"]} >= {"simple", "implementation", "continuation"}
    assert "user_prompt_improve" in {case["hook"] for case in report["cases"]}
    assert "METRIC hook_cost_score=" in result.stdout
    assert "METRIC hook_total_p50_ms=" in result.stdout
    assert "METRIC hook_output_context_units=" in result.stdout
    assert metric_text.startswith("hook_cost_score=")


def test_hook_runtime_cost_benchmark_uses_empty_temp_vault(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "hook_runtime_cost_benchmark_test",
        BENCHMARK,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    seen_vault_dirs: set[str] = set()

    def fake_run_once(command, payload, env, iteration):
        seen_vault_dirs.add(env["VAULT_DIR"])
        return 1.0, 0

    monkeypatch.setattr(module, "run_once", fake_run_once)

    report = module.measure(1)

    assert report["hook_cost_score"] == 12.0
    assert len(seen_vault_dirs) == 1
    vault_dir = Path(next(iter(seen_vault_dirs)))
    assert vault_dir.name == "vault-empty"
    assert vault_dir.parent.name.startswith("ralph-hook-cost-")


def test_hook_runtime_cost_benchmark_seeds_continuation_checkpoint(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "hook_runtime_cost_benchmark_test_seed",
        BENCHMARK,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeded: list[tuple[str, int]] = []
    continuity_outputs: list[int] = []

    def fake_seed(payload, iteration, env):
        seeded.append((payload["name"], iteration))

    def fake_run_once(command, payload, env, iteration):
        hook_name = next(
            name
            for name, candidate in module.USER_PROMPT_HOOKS
            if candidate == command
        )
        if payload["name"] == "continuation" and hook_name == "continuity_prompt_context":
            continuity_outputs.append(120)
            return 1.0, 120
        return 1.0, 0

    monkeypatch.setattr(module, "seed_continuation_checkpoint", fake_seed)
    monkeypatch.setattr(module, "run_once", fake_run_once)

    report = module.measure(2)

    assert seeded == [("continuation", 0), ("continuation", 1)]
    assert continuity_outputs == [120, 120]
    continuation_case = next(
        case
        for case in report["cases"]
        if case["payload"] == "continuation" and case["hook"] == "continuity_prompt_context"
    )
    assert continuation_case["stdout_chars"] == 120
