from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evals" / "implementation_progress_baseline.py"


def load_baseline():
    spec = importlib.util.spec_from_file_location("implementation_progress_baseline_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_percentile_and_context_unit_heuristic_are_deterministic() -> None:
    module = load_baseline()
    assert module.percentile([1, 2, 3, 4], 50) == 3
    assert module.percentile([1, 2, 3, 4], 95) == 4
    assert module.estimate_context_units(0) == 0
    assert module.estimate_context_units(1) == 1
    assert module.estimate_context_units(4) == 1
    assert module.estimate_context_units(5) == 2


def test_snapshot_delta_distinguishes_append_replacement_and_mtime(tmp_path: Path) -> None:
    module = load_baseline()
    fixture = object.__new__(module.Fixture)
    fixture.root = tmp_path
    fixture.runtime = tmp_path / "runtime"
    fixture.plan = tmp_path / "plan.md"
    fixture.notes = tmp_path / "notes.html"
    fixture.branch = "baseline-branch"
    fixture.sha = "fixture-sha"
    fixture.session_id = "fixture-session"
    root = tmp_path / ".ralph"
    root.mkdir()
    before_file = root / "events.jsonl"
    before_file.write_text("one\n", encoding="utf-8")
    before = module.snapshot_tree(fixture)
    before_file.write_text("one\ntwo\n", encoding="utf-8")
    os.utime(before_file, ns=(before_file.stat().st_atime_ns, before_file.stat().st_mtime_ns + 1000))
    after = module.snapshot_tree(fixture)
    counters = module.Counters()
    delta = module.snapshot_delta(before, after, counters)
    assert delta.files_written == 1
    assert delta.appends_observed == 1
    assert delta.mtime_ns_changes == 1
    assert delta.bytes_delta == len("two\n".encode())


def test_small_baseline_is_complete_private_and_provider_local(monkeypatch) -> None:
    module = load_baseline()
    current_head = module._run_git(module.ROOT, ["rev-parse", "HEAD"])

    real_run_git = module._run_git

    def run_git_without_origin_main(cwd, args, **kwargs):
        if args == ["rev-parse", "origin/main"]:
            raise AssertionError("base override must not require origin/main")
        return real_run_git(cwd, args, **kwargs)

    monkeypatch.setattr(module, "_run_git", run_git_without_origin_main)
    report = module.run_baseline(sample_count=1, repeats=1, base_sha_override=current_head)
    expected = {
        "ordinary_prompt",
        "first_continuation",
        "repeated_unchanged_continuation",
        "changed_notes_hash",
        "new_session",
        "resume",
        "compact",
        "ambiguous_active_plans",
        "explicit_context_request",
        "create_notes",
        "append_material_entry",
        "idempotent_append_retry",
        "checkpoint_update",
        "checkpoint_unchanged_update",
        "prompt_context_cache_hit",
        "stop_allow",
        "terminal_stop_retry",
    }
    cases = {case["name"] for case in report["cases"]}
    assert cases == expected
    assert report["base_sha"] == current_head
    assert report["origin_main"] == "unknown (base_sha_override)"
    provider = report["provider_accounting"]
    assert provider["actual_external_model_calls"] == 0
    assert provider["actual_advisor_calls"] == 0
    assert provider["actual_worker_calls"] == 0
    assert provider["provider_usage_accounting"] == "unknown"
    assert provider["subscription_usage_accounting"] == "unknown"
    ambiguous = next(case for case in report["cases"] if case["name"] == "ambiguous_active_plans")
    assert ambiguous["progress_output_bytes"]["p50"] == 0
    required_counters = {
        "notes_bytes_read",
        "plan_read_count",
        "index_read_count",
        "html_parse_count",
        "git_subprocess_count",
        "recursive_scan_count",
        "recursive_scan_bytes",
        "recursive_scan_ms",
        "advisor_invocation_count",
        "worker_invocation_count",
        "fsync_relevant_publications",
    }
    required_writes = {
        "files_written",
        "bytes_written_estimate",
        "replacements_observed",
        "appends_observed",
        "mtime_ns_changes",
    }
    for case in report["cases"]:
        assert required_counters <= set(case["counters"])
        assert required_writes <= set(case["writes"])
    rendered = module.markdown_report(report)
    assert "unknown" in rendered
    assert "fsync-relevant publications" in rendered
    assert "mtime changes" in rendered
    assert "Scan ms" in rendered
    assert "+104 bytes over target" in rendered
    assert module.PROMPT_SENTINEL not in rendered
    assert module.NOTE_SENTINEL not in rendered
    assert str(Path.home()) not in rendered
    json.dumps(report, sort_keys=True)
