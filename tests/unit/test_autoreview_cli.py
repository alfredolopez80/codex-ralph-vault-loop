from __future__ import annotations

from pathlib import Path

from autoreview_test_utils import ROOT, cli_args, load_module


def test_status_output_goes_to_stderr(capsys) -> None:
    cli = load_module("cli")
    args = cli_args()
    cli.print_status(args, ROOT, "branch", "YELLOW", [], 10)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "safety: YELLOW" in captured.err


def test_parallel_test_status_goes_to_stderr(capsys) -> None:
    cli = load_module("cli")
    proc = cli.start_parallel_tests("printf parallel-test", ROOT)
    assert proc.wait() == 0
    log_path = Path(proc.autoreview_log_path)
    assert log_path.read_text(encoding="utf-8") == "parallel-test"
    log_path.unlink()
    captured = capsys.readouterr()
    assert "trusted parallel tests" in captured.err
    assert captured.out == ""


def test_main_preserves_engine_failure(monkeypatch, tmp_path: Path) -> None:
    cli = load_module("cli")
    monkeypatch.setattr(cli, "parse_args", lambda: cli_args())
    patch_review_setup(monkeypatch, cli, tmp_path)
    monkeypatch.setattr(cli, "run_codex", lambda args, repo, prompt: (_ for _ in ()).throw(SystemExit("engine failed")))

    try:
        cli.main()
    except SystemExit as exc:
        assert "engine failed" in str(exc)
    else:
        raise AssertionError("expected original engine failure to propagate")


def test_main_reports_parallel_test_failure_with_engine_failure(monkeypatch, tmp_path: Path) -> None:
    cli = load_module("cli")
    monkeypatch.setattr(cli, "parse_args", lambda: cli_args(parallel_tests="make test"))
    patch_review_setup(monkeypatch, cli, tmp_path)

    class FailedProc:
        autoreview_log_path = "/tmp/autoreview-tests.log"

        def wait(self) -> int:
            return 7

    monkeypatch.setattr(cli, "start_parallel_tests", lambda command, repo: FailedProc())
    monkeypatch.setattr(cli, "run_codex", lambda args, repo, prompt: (_ for _ in ()).throw(SystemExit("engine failed")))

    try:
        cli.main()
    except SystemExit as exc:
        text = str(exc)
        assert "engine failed" in text
        assert "parallel tests failed (7)" in text
        assert "/tmp/autoreview-tests.log" in text
    else:
        raise AssertionError("expected combined engine and test failure")


def test_main_requires_declared_review_pass(monkeypatch) -> None:
    cli = load_module("cli")
    monkeypatch.setattr(cli, "parse_args", lambda: cli_args(review_pass=None))

    try:
        cli.main()
    except SystemExit as exc:
        assert "requires --review-pass 1 or --review-pass 2" in str(exc)
    else:
        raise AssertionError("expected missing review pass to fail closed")


def test_main_adds_bounded_pass_instructions(monkeypatch, tmp_path: Path) -> None:
    cli = load_module("cli")
    captured: dict[str, str] = {}
    monkeypatch.setattr(cli, "parse_args", lambda: cli_args(review_pass=2))
    patch_review_setup(monkeypatch, cli, tmp_path)

    def fake_build_prompt(repo, target, target_ref, bundle, extra_prompt, extra_files):
        captured["extra_prompt"] = extra_prompt
        return "prompt"

    monkeypatch.setattr(cli, "build_prompt", fake_build_prompt)
    monkeypatch.setattr(
        cli,
        "run_codex",
        lambda args, repo, prompt: '{"findings":[],"overall_correctness":"patch is correct","overall_explanation":"ok","overall_confidence":1}',
    )

    assert cli.main() == 0
    assert "review pass 2 of 2" in captured["extra_prompt"]
    assert "do not request another automatic autoreview run" in captured["extra_prompt"]


def patch_review_setup(monkeypatch, cli, repo: Path) -> None:
    monkeypatch.setattr(cli, "repo_root", lambda: repo)
    monkeypatch.setattr(cli, "choose_target", lambda repo, mode, base: ("branch", "origin/main"))
    monkeypatch.setattr(cli, "load_classifier", lambda repo: (lambda prompt, sensitivity: {"classification": "YELLOW", "findings": []}))
    monkeypatch.setattr(cli, "changed_paths", lambda repo, target, target_ref, commit, include_untracked: {"src/app.py"})
    monkeypatch.setattr(cli, "sensitive_path_matches", lambda paths: [])
    monkeypatch.setattr(cli, "build_bundle", lambda args, repo, target, target_ref: ("diff", target_ref))
    monkeypatch.setattr(cli, "build_prompt", lambda repo, target, target_ref, bundle, extra_prompt, extra_files: "prompt")
