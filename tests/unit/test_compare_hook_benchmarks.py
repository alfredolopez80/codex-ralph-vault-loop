from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evals" / "compare_hook_benchmarks.py"


def _module():
    spec = importlib.util.spec_from_file_location("compare_hook_benchmarks_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(*, runtime: float = 100.0, blocks: int = 0, schema: int = 2) -> dict:
    return {
        "schema_version": schema,
        "subscription_usage_measured": False,
        "cases": [
            {
                "event": "Stop",
                "role": "stop_dispatch",
                "scenario": "stop_allow",
                "effective_config": "project_only",
                "source_scope": "project",
                "runtime_p50_ms": runtime,
                "runtime_p95_ms": runtime * 1.1,
                "matched_handler_count": 1,
                "executed_handler_count": 1,
                "output_bytes": 0,
                "estimated_context_units": 0,
                "persisted_bytes_delta": 10,
                "block_count": blocks,
                "continuation_count": blocks,
                "child_process_count": 0,
            }
        ],
    }


def test_compare_classifies_improvement_and_noise() -> None:
    module = _module()
    improvement = module.compare(_report(runtime=100), _report(runtime=80), 0.05)
    assert improvement["classification"] == "mejora"
    noise = module.compare(_report(runtime=100), _report(runtime=103), 0.05)
    assert noise["classification"] == "ruido"


def test_compare_rejects_semantic_change_as_non_comparable() -> None:
    module = _module()
    result = module.compare(_report(), _report(blocks=1), 0.05)
    assert result["classification"] == "cambio no comparable"
    assert result["semantic_changes"]


def test_compare_rejects_incompatible_schema(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps(_report(schema=1)), encoding="utf-8")
    candidate.write_text(json.dumps(_report()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--baseline", str(baseline), "--candidate", str(candidate)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "cambio no comparable" in result.stderr
