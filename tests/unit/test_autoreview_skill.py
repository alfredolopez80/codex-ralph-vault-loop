from __future__ import annotations

import importlib.util
import subprocess
import sys
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


def test_fallback_classifier_blocks_sensitive_bundle() -> None:
    safety = load_module("safety")
    sample = "api_" + "key=fixture-value"
    report = safety.fallback_classify_text(sample, "YELLOW")
    assert report["classification"] == "RED"
    assert report["findings"]


def test_sensitive_path_guard_blocks_extra_context() -> None:
    safety = load_module("safety")
    assert safety.is_path_sensitive("." + "env.local")
    assert safety.is_path_sensitive("logs/service.log")
    assert safety.is_path_sensitive("private/credential.txt")
    assert safety.sensitive_path_matches({"config/prod-token.txt", "src/app.py"}) == ["config/prod-token.txt"]


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
