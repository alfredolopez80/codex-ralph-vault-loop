from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTEXT_DIR = ROOT / "scripts" / "context"
FIXTURES = ROOT / "tests" / "fixtures" / "context_helpers"
sys.path.insert(0, str(CONTEXT_DIR))

import compact_logs  # noqa: E402
import context_common  # noqa: E402
import repo_map  # noqa: E402
import scan_errors  # noqa: E402
import summarize_data  # noqa: E402
import summarize_json  # noqa: E402


def test_context_scripts_have_help() -> None:
    for script in [
        "repo_map.py",
        "scan_errors.py",
        "summarize_json.py",
        "summarize_data.py",
        "compact_logs.py",
    ]:
        result = subprocess.run(
            [sys.executable, str(CONTEXT_DIR / script), "--help"],
            check=False,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout


def test_common_preview_redacts_sensitive_values() -> None:
    sensitive = "api_" + "key=fixturevalue"

    rendered = context_common.preview(sensitive)

    assert "fixturevalue" not in rendered
    assert "[REDACTED:" in rendered


def test_common_read_text_bounded_reads_only_requested_prefix(tmp_path: Path) -> None:
    large = tmp_path / "large.json"
    large.write_text("a" * 100 + "tail-marker", encoding="utf-8")

    text, truncated = context_common.read_text_bounded(large, max_bytes=20)

    assert text == "a" * 20
    assert truncated is True
    assert "tail-marker" not in text


def test_repo_map_is_concise_and_skips_noisy_paths(tmp_path: Path) -> None:
    (tmp_path / ".codex" / "hooks").mkdir(parents=True)
    (tmp_path / ".codex" / "hooks" / "pre_tool_guard.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_run.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"not-real-image")

    report = repo_map.build_map(tmp_path, max_files=20, max_depth=4)
    rendered = repo_map.render_markdown(report)

    assert ".codex/hooks/pre_tool_guard.py" in report["surfaces"]["hook_surfaces"]
    assert "scripts/run.py" in report["surfaces"]["entry_points"]
    assert "tests/test_run.py" in report["surfaces"]["test_surfaces"]
    assert "node_modules" not in rendered
    assert "image.png" not in rendered


def test_scan_errors_groups_findings_and_keeps_small_context() -> None:
    report = scan_errors.summarize([FIXTURES / "sample.log"], limit=5, context_lines=1, pattern_text=scan_errors.DEFAULT_PATTERN)
    rendered = scan_errors.render_markdown(report)

    assert report["match_count"] == 2
    assert "warning cache lookup slow" in rendered
    assert "error worker failed" in rendered
    assert "service starting" in rendered


def test_summarize_json_reports_shape_without_full_dump() -> None:
    report = summarize_json.summarize(FIXTURES / "sample.json", max_items=10, max_depth=3, include_samples=True)
    rendered = summarize_json.render_markdown(report)

    assert report["root_type"] == "object"
    assert "meta" in report["top_level_keys"]
    assert "$.results[0].id" in rendered
    assert "Top-Level Samples" in rendered


def test_summarize_data_handles_csv_tsv_and_jsonl() -> None:
    csv_report = summarize_data.summarize(FIXTURES / "sample.csv", limit_rows=1000, sample=2)
    tsv_report = summarize_data.summarize(FIXTURES / "sample.tsv", limit_rows=1000, sample=2)
    jsonl_report = summarize_data.summarize(FIXTURES / "sample.jsonl", limit_rows=1000, sample=2)

    assert csv_report["kind"] == "csv"
    assert csv_report["empty_counts"]["value"] == 1
    assert tsv_report["kind"] == "tsv"
    assert jsonl_report["kind"] == "jsonl"
    assert "message" in jsonl_report["columns"]


def test_compact_logs_uses_timestamp_window_and_keyword_filter() -> None:
    report = compact_logs.compact(
        [FIXTURES / "sample.jsonl"],
        hours=1,
        keywords=["error"],
        regex_text=None,
        limit=5,
    )
    rendered = compact_logs.render_markdown(report)

    assert report["mode"] == "timestamp-window"
    assert len(report["selected"]) == 1
    assert "error retry failed" in rendered
    assert "info heartbeat" not in rendered
