from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "autoresearch"))

from common import AutoResearchError  # noqa: E402
from generation import REQUIRED_JSON_ARTIFACTS, REQUIRED_TEXT_ARTIFACTS, safe_id, write_generation_bundle  # noqa: E402


def test_generation_bundle_writes_required_scanned_files(tmp_path: Path) -> None:
    result = write_generation_bundle(
        tmp_path,
        "segment-1",
        {
            "generation_id": "gen_000",
            "candidate_patch": "No patch.\n",
            "stdout": "METRIC seconds=1\n",
            "stderr": "",
            "command": {"benchmark_command": "printf metric", "cwd": str(tmp_path)},
            "metrics": {"seconds": 1.0},
            "checks": {"benchmark_returncode": 0},
            "hard_gates": {"tests_pass": True, "no_secret_leak": True},
            "decision": {"status": "pending"},
            "asi": {"hypothesis": "", "evidence": "", "next_action_hint": ""},
            "trace": {"fingerprint": "abc"},
        },
    )

    root = Path(result["path"])
    for filename in (
        "manifest.json",
        "candidate.patch",
        "command.json",
        "benchmark.stdout.preview.txt",
        "benchmark.stderr.preview.txt",
        "metrics.json",
        "checks.json",
        "hard_gates.json",
        "decision.json",
        "asi.json",
        "improvement.md",
        "trace.json",
        "scan_report.json",
    ):
        assert (root / filename).is_file()
    assert json.loads((root / "metrics.json").read_text(encoding="utf-8"))["seconds"] == 1.0
    scan_report = json.loads((root / "scan_report.json").read_text(encoding="utf-8"))
    expected = set(REQUIRED_JSON_ARTIFACTS) | set(REQUIRED_TEXT_ARTIFACTS)
    assert set(scan_report["required_artifacts"]) == expected
    assert set(scan_report["scanned_artifacts"]) == expected
    assert all(record["scan_status"] == "pass" for record in scan_report["scanned_artifacts"].values())


def test_generation_bundle_rejects_unsafe_ids_and_red_content(tmp_path: Path) -> None:
    for value in ("../segment", ".hidden", "segment/path"):
        try:
            safe_id("segment_id", value)
        except AutoResearchError:
            pass
        else:
            raise AssertionError(f"accepted unsafe id {value}")

    red_marker = "secret" + "=abc123\n"
    try:
        write_generation_bundle(
            tmp_path,
            "segment-1",
            {
                "candidate_patch": red_marker,
                "command": {},
                "metrics": {},
                "checks": {},
                "hard_gates": {},
                "decision": {},
                "asi": {},
                "trace": {},
            },
        )
    except AutoResearchError:
        pass
    else:
        raise AssertionError("accepted RED generation content")


def test_generation_bundle_rejects_red_content_in_each_persisted_artifact(tmp_path: Path) -> None:
    red_marker = "secret" + "=abc123"
    cases = {
        "candidate_patch": {"candidate_patch": red_marker},
        "stdout_preview": {"stdout": red_marker},
        "stderr_preview": {"stderr": red_marker},
        "improvement": {"improvement": red_marker},
        "command": {"command": {"benchmark_command": red_marker}},
        "metrics": {"metrics": {"note": red_marker}},
        "checks": {"checks": {"note": red_marker}},
        "hard_gates": {"hard_gates": {"note": red_marker}},
        "decision": {"decision": {"note": red_marker}},
        "asi": {"asi": {"note": red_marker}},
        "trace": {"trace": {"note": red_marker}},
    }
    base_payload = {
        "candidate_patch": "No patch.\n",
        "stdout": "METRIC seconds=1\n",
        "stderr": "",
        "command": {"benchmark_command": "printf metric"},
        "metrics": {"seconds": 1.0},
        "checks": {"benchmark_returncode": 0},
        "hard_gates": {"tests_pass": True, "no_secret_leak": True},
        "decision": {"status": "pending"},
        "asi": {"hypothesis": "", "evidence": "", "next_action_hint": ""},
        "trace": {"fingerprint": "abc"},
    }

    for artifact, override in cases.items():
        payload = base_payload | override | {"generation_id": f"gen_{len(artifact):03d}"}
        try:
            write_generation_bundle(tmp_path / artifact, "segment-1", payload)
        except AutoResearchError:
            pass
        else:
            raise AssertionError(f"accepted RED content in {artifact}")


def test_generation_bundle_rejects_symlinked_run_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "autoresearch.runs").symlink_to(outside)

    try:
        write_generation_bundle(
            tmp_path,
            "segment-1",
            {
                "candidate_patch": "No patch.\n",
                "command": {},
                "metrics": {},
                "checks": {},
                "hard_gates": {},
                "decision": {},
                "asi": {},
                "trace": {},
            },
        )
    except AutoResearchError:
        pass
    else:
        raise AssertionError("accepted symlinked generation root")
