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

    def fake_run_once(command, payload, env):
        seen_vault_dirs.add(env["VAULT_DIR"])
        return 1.0, 0

    monkeypatch.setattr(module, "run_once", fake_run_once)

    report = module.measure(1)

    assert report["hook_cost_score"] == 9.0
    assert len(seen_vault_dirs) == 1
    vault_dir = Path(next(iter(seen_vault_dirs)))
    assert vault_dir.name == "vault-empty"
    assert vault_dir.parent.name.startswith("ralph-hook-cost-")
