"""Local, provider-free benchmark for one store update and its retry."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from shared.implementation_store import ImplementationStore, resolve_store_paths  # noqa: E402


def _run_git(cwd: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git fixture command failed")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "p50_ms": round(_percentile(values, 0.50) * 1000, 3),
        "p95_ms": round(_percentile(values, 0.95) * 1000, 3),
        "min_ms": round(min(values) * 1000, 3),
        "max_ms": round(max(values) * 1000, 3),
    }


def run(samples: int = 20) -> dict[str, object]:
    if samples < 2 or samples > 200:
        raise ValueError("samples must be between 2 and 200")
    # macOS commonly exposes /var as a symlink to /private/var.  The store's
    # deliberately strict resolver rejects that alias, so keep the fixture in
    # the real temporary root used by the test environment.
    temporary_root = "/private/tmp" if Path("/private/tmp").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="implementation-store-bench-", dir=temporary_root) as temporary:
        root = Path(temporary) / "primary" / "project"
        root.mkdir(parents=True)
        _run_git(root, "init")
        _run_git(root, "config", "user.name", "Benchmark Fixture")
        _run_git(root, "config", "user.email", "benchmark@example.invalid")
        (root / "README.md").write_text("benchmark\n", encoding="utf-8")
        _run_git(root, "add", "README.md")
        _run_git(root, "commit", "-m", "benchmark fixture")
        store = ImplementationStore(resolve_store_paths(primary_root=root))
        store.register_plan("bench", now="2026-08-10T00:00:00+00:00")
        plan = store.plan_paths("bench")

        material_latency: list[float] = []
        retry_latency: list[float] = []
        material_appends: list[int] = []
        material_replacements: list[int] = []
        material_bytes: list[int] = []
        material_files: list[int] = []
        retry_bytes: list[int] = []
        retry_files: list[int] = []
        retry_mtime_equal: list[bool] = []
        for index in range(samples):
            operation = f"bench-{index}"
            started = time.perf_counter()
            material = store.update_state(
                "bench",
                {"phase": f"phase-{index}"},
                kind="phase_changed",
                operation_id=operation,
            )
            material_latency.append(time.perf_counter() - started)
            material_appends.append(material.metadata.appends)
            material_replacements.append(material.metadata.replacements)
            material_bytes.append(material.metadata.bytes_written)
            material_files.append(len(material.metadata.files_written))

            before = plan.state.stat().st_mtime_ns
            started = time.perf_counter()
            retry = store.update_state(
                "bench",
                {"phase": f"phase-{index}"},
                kind="phase_changed",
                operation_id=operation,
            )
            retry_latency.append(time.perf_counter() - started)
            retry_bytes.append(retry.metadata.bytes_written)
            retry_files.append(len(retry.metadata.files_written))
            retry_mtime_equal.append(plan.state.stat().st_mtime_ns == before)

        return {
            "samples": samples,
            "provider_calls": 0,
            "material_update": {
                **_summary(material_latency),
                "max_bytes_written": max(material_bytes),
                "max_files_written": max(material_files),
                "max_appends": max(material_appends),
                "max_replacements": max(material_replacements),
            },
            "unchanged_retry": {
                **_summary(retry_latency),
                "max_bytes_written": max(retry_bytes),
                "max_files_written": max(retry_files),
                "all_mtime_unchanged": all(retry_mtime_equal),
            },
            "noise_bound": "local scheduler/filesystem variance; compare medians and p95 on the same machine",
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    print(json.dumps(run(parser.parse_args().samples), sort_keys=True))
