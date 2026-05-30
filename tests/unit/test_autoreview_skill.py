from __future__ import annotations

import importlib.util
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "skills" / "autoreview" / "scripts"


def load_module(name: str):
    sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_trusted_classifier_fails_closed() -> None:
    safety = load_module("safety")
    try:
        safety.fail_closed_classifier("public text", "YELLOW")
    except SystemExit as exc:
        assert "trusted sensitive-content classifier" in str(exc)
    else:
        raise AssertionError("expected missing classifier to fail closed")


def test_sensitive_path_guard_blocks_extra_context() -> None:
    safety = load_module("safety")
    assert safety.is_path_sensitive("." + "env.local")
    assert safety.is_path_sensitive("logs/service.log")
    assert safety.is_path_sensitive("private/credential.txt")
    assert safety.sensitive_path_matches({"config/prod-token.txt", "src/app.py"}) == ["config/prod-token.txt"]


def test_malformed_classifier_result_fails_closed() -> None:
    safety = load_module("safety")
    try:
        safety.report_classification({})
    except SystemExit as exc:
        assert "malformed sensitive-content classifier result" in str(exc)
    else:
        raise AssertionError("expected malformed classifier output to fail closed")


def test_status_output_goes_to_stderr(capsys) -> None:
    cli = load_module("cli")
    args = SimpleNamespace(engine="codex", web_search=False, fetch=False, include_untracked=False)
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


def test_heartbeat_does_not_resend_stdin_after_timeout(tmp_path: Path) -> None:
    review = load_module("review")
    code = "import sys, time; data = sys.stdin.read(); time.sleep(0.15); print(data)"
    result = review.run_with_heartbeat(
        [sys.executable, "-c", code],
        tmp_path,
        input_text="payload",
        label="test",
        heartbeat_seconds=0.01,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "payload"


def test_build_prompt_omits_absolute_repo_path(tmp_path: Path) -> None:
    review = load_module("review")
    repo = tmp_path / "repo"
    repo.mkdir()
    prompt = review.build_prompt(repo, "branch", "origin/main", "diff --git a/x b/x", "", "")
    assert str(repo) not in prompt
    assert "Repository label: repo" in prompt
    assert "sanitized temporary directory" in prompt


def test_run_codex_uses_sanitized_workspace(tmp_path: Path, monkeypatch) -> None:
    review = load_module("review")
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")

    def fake_run_with_heartbeat(cmd, cwd, *, input_text, label, heartbeat_seconds=60, env=None):
        cmd_text = " ".join(cmd)
        workspace = Path(cmd[cmd.index("-C") + 1])
        assert input_text == "prompt"
        assert label == "codex"
        assert cwd == workspace
        assert repo != workspace
        assert repo not in workspace.parents
        assert str(repo) not in cmd_text
        assert "--skip-git-repo-check" in cmd
        assert "--ignore-user-config" in cmd
        assert "--ignore-rules" in cmd
        assert env is not None
        assert "AWS_SECRET_ACCESS_KEY" not in env
        return subprocess.CompletedProcess(cmd, 0, '{"findings":[],"overall_correctness":"patch is correct","overall_explanation":"ok","overall_confidence":1}', "")

    monkeypatch.setattr(review, "run_with_heartbeat", fake_run_with_heartbeat)
    args = SimpleNamespace(codex_bin="codex", web_search=False, model=None)
    raw = review.run_codex(args, repo, "prompt")
    assert '"overall_correctness":"patch is correct"' in raw


def test_repo_file_guard_rejects_symlinks(tmp_path: Path) -> None:
    safety = load_module("safety")
    target = tmp_path / "target.txt"
    target.write_text("public", encoding="utf-8")
    link = tmp_path / "notes.txt"
    link.symlink_to(target)
    try:
        safety.assert_safe_repo_file(tmp_path, "notes.txt", context="dataset")
    except SystemExit as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("expected symlink path to be rejected")


def test_output_guard_rejects_symlink(tmp_path: Path) -> None:
    safety = load_module("safety")
    target = tmp_path / "target.txt"
    target.write_text("old", encoding="utf-8")
    link = tmp_path / "report.txt"
    link.symlink_to(target)
    try:
        safety.resolve_safe_repo_output(tmp_path, "report.txt", context="output")
    except SystemExit as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("expected symlink output path to be rejected")


def test_local_bundle_fails_when_untracked_files_are_omitted(tmp_path: Path) -> None:
    git_bundle = load_module("git_bundle")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "AutoReview Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "autoreview@example.test"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "init"], cwd=tmp_path, check=True)
    (tmp_path / "new.txt").write_text("new", encoding="utf-8")
    try:
        git_bundle.local_bundle(tmp_path, include_untracked=False)
    except SystemExit as exc:
        assert "untracked files omitted" in str(exc)
    else:
        raise AssertionError("expected untracked local review to fail closed")


def test_repo_classifier_must_match_origin_main(tmp_path: Path) -> None:
    safety = load_module("safety")
    classifier = tmp_path / "scripts" / "security" / "sensitive_content.py"
    classifier.parent.mkdir(parents=True)
    classifier.write_text("def classify_text(text, requested=None): return {'classification': 'GREEN', 'findings': []}\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "AutoReview Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "autoreview@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "scripts/security/sensitive_content.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True)
    assert safety.classifier_is_unchanged(tmp_path, classifier)
    classifier.write_text("def classify_text(text, requested=None): return {'classification': 'YELLOW', 'findings': []}\n", encoding="utf-8")
    assert not safety.classifier_is_unchanged(tmp_path, classifier)


def finding_at(path: str) -> dict[str, object]:
    return {
        "title": "Shared guard now allows unsafe caller",
        "body": "The changed helper reaches this unchanged endpoint and bypasses its guard.",
        "priority": "P1",
        "confidence": 0.8,
        "category": "security",
        "code_location": {"file_path": path, "line": 42},
    }


def report_with(path: str) -> dict[str, object]:
    return {
        "findings": [finding_at(path)],
        "overall_correctness": "patch is incorrect",
        "overall_explanation": "The change weakens a shared guard.",
        "overall_confidence": 0.8,
    }


def test_supporting_findings_are_preserved_by_default() -> None:
    review = load_module("review")
    report = report_with("src/endpoint.py")
    review.validate_report(report, {"src/helper.py"}, strict_changed_paths=False)
    assert len(report["findings"]) == 1


def test_supporting_findings_can_be_strictly_dropped() -> None:
    review = load_module("review")
    report = report_with("src/endpoint.py")
    review.validate_report(report, {"src/helper.py"}, strict_changed_paths=True)
    assert report["findings"] == []
    assert report["overall_correctness"] == "patch is correct"


def test_review_validator_rejects_extra_code_location_keys() -> None:
    review = load_module("review")
    report = report_with("src/helper.py")
    report["findings"][0]["code_location"]["end_line"] = 43
    try:
        review.validate_report(report, {"src/helper.py"}, strict_changed_paths=False)
    except SystemExit as exc:
        assert "code_location has unexpected keys" in str(exc)
    else:
        raise AssertionError("expected schema-invalid code_location to be rejected")


def test_review_validator_rejects_long_overall_explanation() -> None:
    review = load_module("review")
    report = report_with("src/helper.py")
    report["overall_explanation"] = "x" * 3201
    try:
        review.validate_report(report, {"src/helper.py"}, strict_changed_paths=False)
    except SystemExit as exc:
        assert "overall_explanation" in str(exc)
    else:
        raise AssertionError("expected overlong overall_explanation to be rejected")


def test_strict_changed_paths_note_stays_schema_bounded() -> None:
    review = load_module("review")
    report = report_with("src/endpoint.py")
    report["overall_explanation"] = "x" * 3200
    review.validate_report(report, {"src/helper.py"}, strict_changed_paths=True)
    assert report["findings"] == []
    assert report["overall_correctness"] == "patch is correct"
    assert len(report["overall_explanation"]) <= 3200
    assert "outside the changed path set" in report["overall_explanation"]
