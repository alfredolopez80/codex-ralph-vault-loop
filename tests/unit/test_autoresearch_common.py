from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "autoresearch"))

from common import default_hard_gates, latest_baseline, parse_metrics, validate_asi  # noqa: E402


def run_script(script: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "autoresearch" / script), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_parse_metrics_accepts_named_finite_values() -> None:
    output = "noise\nMETRIC seconds=12.34\nMETRIC memory_mb=4e2\n"
    assert parse_metrics(output) == {"seconds": 12.34, "memory_mb": 400.0}


def test_asi_requires_rollback_for_rejected_statuses() -> None:
    missing = validate_asi({"hypothesis": "x", "evidence": "y", "next_action_hint": "z"}, "discard")
    assert "rollback_reason" in missing
    assert validate_asi({"hypothesis": "x", "evidence": "y", "next_action_hint": "z"}, "keep") == []


def test_best_kept_baseline_uses_direction() -> None:
    entries = [
        {"status": "keep", "metrics": {"seconds": 3, "score": 0.2}},
        {"status": "discard", "metrics": {"seconds": 1, "score": 0.9}},
        {"status": "keep", "metrics": {"seconds": 2, "score": 0.4}},
    ]

    assert latest_baseline(entries, "seconds", "lower", "best_kept") == 2
    assert latest_baseline(entries, "score", "higher", "best_kept") == 0.4
    assert latest_baseline(entries, "seconds", "lower", "initial") == 3
    assert latest_baseline(entries, "seconds", "lower", "latest_kept") == 2


def test_hard_gates_detect_red_output() -> None:
    red_text = "api_key" + "=fixture-value"
    gates = default_hard_gates(True, red_text)
    assert gates["tests_pass"] is True
    assert gates["no_secret_leak"] is False
    assert gates["finite_primary_metric"] is True


def test_cli_setup_rejects_red_goal(tmp_path: Path) -> None:
    red_text = "secret" + "=abc123"
    result = run_script(
        "setup.py",
        "--cwd",
        str(tmp_path),
        "--goal",
        red_text,
        "--metric",
        "seconds",
        "--direction",
        "lower",
        "--benchmark-command",
        "printf 'METRIC seconds=1\\n'",
    )
    assert result.returncode == 1
    assert red_text not in result.stderr


def test_cli_loop_logs_keep_and_rejects_stale_packet(tmp_path: Path) -> None:
    setup = run_script(
        "setup.py",
        "--cwd",
        str(tmp_path),
        "--goal",
        "speed loop",
        "--metric",
        "seconds",
        "--direction",
        "lower",
        "--benchmark-command",
        "printf 'METRIC seconds=1\\n'",
        "--commit-paths",
        "src",
    )
    assert setup.returncode == 0, setup.stderr

    first = run_script("next.py", "--cwd", str(tmp_path))
    assert first.returncode == 0, first.stderr
    logged = run_script("log.py", "--cwd", str(tmp_path), "--from-last", "--status", "keep", "--description", "baseline")
    assert logged.returncode == 0, logged.stderr
    ledger_lines = (tmp_path / "autoresearch.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(ledger_lines[-1])["status"] == "keep"

    second = run_script("next.py", "--cwd", str(tmp_path))
    assert second.returncode == 0, second.stderr
    (tmp_path / "new-file.txt").write_text("changed after packet\n", encoding="utf-8")
    stale = run_script("log.py", "--cwd", str(tmp_path), "--from-last", "--status", "discard", "--description", "stale")
    assert stale.returncode == 1
    assert "stale" in stale.stderr


def test_cli_generation_spine_writes_bundle(tmp_path: Path) -> None:
    setup = run_script(
        "setup.py",
        "--cwd",
        str(tmp_path),
        "--goal",
        "generation loop",
        "--metric",
        "seconds",
        "--direction",
        "lower",
        "--benchmark-command",
        "printf 'METRIC seconds=1\\n'",
        "--generation-spine",
    )
    assert setup.returncode == 0, setup.stderr

    packet = run_script("next.py", "--cwd", str(tmp_path))

    assert packet.returncode == 0, packet.stderr
    payload = json.loads(packet.stdout)
    generation = payload["generation"]
    assert Path(generation["path"]).is_dir()
    assert Path(generation["files"]["hard_gates"]).is_file()


def test_cli_crash_can_log_without_metric(tmp_path: Path) -> None:
    setup = run_script(
        "setup.py",
        "--cwd",
        str(tmp_path),
        "--goal",
        "crash loop",
        "--metric",
        "seconds",
        "--direction",
        "lower",
        "--benchmark-command",
        "printf 'no metric\\n'",
    )
    assert setup.returncode == 0, setup.stderr
    packet = run_script("next.py", "--cwd", str(tmp_path))
    assert packet.returncode == 0, packet.stderr
    asi = json.dumps(
        {
            "hypothesis": "missing metric path",
            "evidence": "benchmark did not emit the primary metric",
            "rollback_reason": "no candidate evidence",
            "next_action_hint": "fix benchmark output before continuing",
        }
    )
    logged = run_script("log.py", "--cwd", str(tmp_path), "--from-last", "--status", "crash", "--asi", asi)
    assert logged.returncode == 0, logged.stderr


def test_cli_rejects_keep_when_hard_gate_fails(tmp_path: Path) -> None:
    red_line = "api_" + "key=fixture-value"
    setup = run_script(
        "setup.py",
        "--cwd",
        str(tmp_path),
        "--goal",
        "red output loop",
        "--metric",
        "seconds",
        "--direction",
        "lower",
        "--benchmark-command",
        f"printf 'METRIC seconds=1\\n{red_line}\\n'",
    )
    assert setup.returncode == 0, setup.stderr

    packet = run_script("next.py", "--cwd", str(tmp_path))
    assert packet.returncode == 0, packet.stderr
    logged = run_script("log.py", "--cwd", str(tmp_path), "--from-last", "--status", "keep", "--description", "bad keep")

    assert logged.returncode == 1
    assert "hard gates failed" in logged.stderr
