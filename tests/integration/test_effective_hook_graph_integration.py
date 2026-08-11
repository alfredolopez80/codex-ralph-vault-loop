from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_effective_hook_graph_doctor_passes_project_and_global_snapshot() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/gates/effective-hook-graph.py"), "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] in {"PASS", "WARN"}
    assert all(domain["status"] == "PASS" for domain in payload["domains"])
    assert payload["legacy_wrapper_registered"] is False
