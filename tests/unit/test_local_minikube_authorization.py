from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"
sys.path.insert(0, str(HOOKS))

from shared.local_minikube_grant import allows, digest, targets  # noqa: E402
from shared.cloud_operation_gate import ContextVerification, assess_command  # noqa: E402
from shared import cloud_operation_gate  # noqa: E402


def write_grant(grant_root: Path, patch: str, target: Path, *, expired: bool = False) -> None:
    grant_root.mkdir(mode=0o700, exist_ok=True)
    path = grant_root / f"{digest(patch)}.approved"
    path.write_text("", encoding="utf-8")
    path.chmod(0o600)
    if expired:
        old = path.stat().st_mtime - 901
        os.utime(path, (old, old))


def test_grant_requires_exact_patch_target_and_unexpired_hash(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    target = notes / "seed.sh"
    marker = "PASS" + "WORD"
    patch = f"*** Begin Patch\n*** Add File: .local-notes/seed.sh\n+{marker}=generated\n*** End Patch"
    grant_root = tmp_path / "grants"
    monkeypatch.setenv("CODEX_LOCAL_GRANT_ROOT", str(grant_root))
    write_grant(grant_root, patch, target)

    assert allows(patch, tmp_path)
    assert not allows(patch + "\n", tmp_path)
    assert targets(patch.replace(".local-notes", "scripts"), tmp_path) is None


def test_grant_rejects_expired_or_group_readable_file(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    target = notes / "seed.sh"
    patch = "*** Begin Patch\n*** Add File: .local-notes/seed.sh\n+hello\n*** End Patch"
    grant_root = tmp_path / "grants"
    monkeypatch.setenv("CODEX_LOCAL_GRANT_ROOT", str(grant_root))
    write_grant(grant_root, patch, target, expired=True)
    assert not allows(patch, tmp_path)

    write_grant(grant_root, patch, target)
    (grant_root / f"{digest(patch)}.approved").chmod(0o640)
    assert not allows(patch, tmp_path)


def test_grant_rejects_tracked_local_notes_target(tmp_path: Path) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    target = notes / "seed.sh"
    target.write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "add", str(target)], cwd=tmp_path, capture_output=True, check=True)
    patch = "*** Begin Patch\n*** Update File: .local-notes/seed.sh\n+hello\n*** End Patch"
    assert targets(patch, tmp_path) is None

def test_pre_tool_guard_uses_exact_local_grant(tmp_path: Path) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    target = notes / "seed.sh"
    marker = "PASS" + "WORD"
    patch = f"*** Begin Patch\n*** Add File: .local-notes/seed.sh\n+{marker}=generated\n*** End Patch"
    grant_root = tmp_path / "grants"
    write_grant(grant_root, patch, target)
    env = os.environ.copy()
    env["CODEX_LOCAL_GRANT_ROOT"] = str(grant_root)
    result = subprocess.run(
        [sys.executable, str(HOOKS / "pre_tool_guard.py")],
        input=json.dumps({"tool_input": {"patch": patch, "cwd": str(tmp_path)}}),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_pre_tool_guard_allows_untracked_local_notes_patch_without_grant(tmp_path: Path) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    marker = "PASS" + "WORD"
    patch = f"*** Begin Patch\n*** Add File: .local-notes/seed.sh\n+{marker}=generated\n*** End Patch"
    grant_root = tmp_path / "grants"
    env = os.environ.copy()
    env["CODEX_LOCAL_GRANT_ROOT"] = str(grant_root)
    result = subprocess.run(
        [sys.executable, str(HOOKS / "pre_tool_guard.py")],
        input=json.dumps({"tool_input": {"patch": patch, "cwd": str(tmp_path)}}),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def run_guard(tmp_path: Path, command: str, grant_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CODEX_LOCAL_GRANT_ROOT"] = str(grant_root)
    return subprocess.run(
        [sys.executable, str(HOOKS / "pre_tool_guard.py")],
        input=json.dumps({"tool_input": {"command": command, "cwd": str(tmp_path)}}),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_cloud_reads_pass_and_mutations_request_human_approval(tmp_path: Path) -> None:
    grant_root = tmp_path / "approvals"
    reads = [
        "aws ec2 describe-instances",
        "gcloud compute instances list",
        "terraform plan",
        "minikube status",
        "helm list",
    ]
    mutations = [
        "aws s3 cp artifact s3://bucket/artifact",
        "gcloud run deploy service",
        "terraform apply plan.tfplan",
        "minikube stop",
        "helm upgrade service chart/",
    ]
    for command in reads:
        assert run_guard(tmp_path, command, grant_root).stdout == "", command
    for command in mutations:
        payload = json.loads(run_guard(tmp_path, command, grant_root).stdout)
        assert payload["reason_code"] == "cloud_command_approval_required"
        assert payload["risk_level"] == "mutating"
        assert "approve-risky-command" in payload["suggested_command"]

    missing_context = json.loads(run_guard(tmp_path, "kubectl get pods", grant_root).stdout)
    assert missing_context["reason_code"] == "kubectl_context_required"


def test_destructive_command_approval_is_exact_and_one_use(tmp_path: Path) -> None:
    grant_root = tmp_path / "approvals"
    command = "aws ec2 terminate-instances --instance-ids i-example"
    blocked = json.loads(run_guard(tmp_path, command, grant_root).stdout)
    assert blocked["risk_level"] == "destructive"
    grant_root.mkdir(mode=0o700)
    marker = grant_root / f"command-{digest(command)}.approved"
    marker.write_text("", encoding="utf-8")
    marker.chmod(0o600)

    assert run_guard(tmp_path, command, grant_root).stdout == ""
    assert not marker.exists()
    retried = json.loads(run_guard(tmp_path, command, grant_root).stdout)
    assert retried["reason_code"] == "cloud_command_approval_required"


def test_script_location_does_not_change_cloud_evaluation(tmp_path: Path) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    scripts = [notes / "seed.sh", tmp_path / "seed.sh"]
    for script in scripts:
        script.write_text("#!/bin/sh\naws s3 cp artifact s3://bucket/artifact\n", encoding="utf-8")
        payload = json.loads(run_guard(tmp_path, f"bash {script}", tmp_path / "approvals").stdout)
        assert payload["tool"] == "aws"
        assert payload["risk_level"] == "mutating"


def test_verified_minikube_allows_mutation_and_ordinary_delete(tmp_path: Path) -> None:
    verify = lambda context: ContextVerification(True, True, "feature-test")
    for command in (
        "kubectl --context feature-test apply -f deployment.yaml",
        "kubectl --context feature-test delete deployment api",
    ):
        assessment = assess_command(command, tmp_path, verify)
        assert assessment.action == "allow"
        assert assessment.profile == "feature-test"
        assert assessment.warning


def test_verified_minikube_complete_delete_still_requires_approval(tmp_path: Path) -> None:
    verify = lambda context: ContextVerification(True, True, "feature-test")
    for command in (
        "kubectl --context feature-test delete namespace feature-test",
        "kubectl --context feature-test delete pods --all",
    ):
        assessment = assess_command(command, tmp_path, verify)
        assert assessment.action == "approval"
        assert assessment.risk_level == "destructive"


def test_non_minikube_context_allows_reads_but_gates_mutations(tmp_path: Path) -> None:
    verify = lambda context: ContextVerification(True, False)
    read = assess_command("kubectl --context live get pods", tmp_path, verify)
    mutation = assess_command("kubectl --context live apply -f deployment.yaml", tmp_path, verify)
    assert read.action == "allow"
    assert mutation.action == "approval"


def test_invalid_or_dynamic_kubectl_context_is_blocked(tmp_path: Path) -> None:
    invalid = lambda context: ContextVerification(False, False)
    missing = assess_command("kubectl get pods", tmp_path, invalid)
    unknown = assess_command("kubectl --context missing get pods", tmp_path, invalid)
    dynamic = assess_command("kubectl --context '$KUBE_CONTEXT' get pods", tmp_path, invalid)
    assert missing.reason_code == "kubectl_context_required"
    assert unknown.reason_code == "kubectl_context_invalid"
    assert dynamic.reason_code == "kubectl_context_not_static"


def test_context_verifier_matches_running_profile_context_and_endpoint(monkeypatch) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, "https://127.0.0.1:8443", ""),
            subprocess.CompletedProcess([], 0, json.dumps({"valid": [{"Name": "feature-test", "Status": "Running"}]}), ""),
            subprocess.CompletedProcess([], 0, "feature-test", ""),
            subprocess.CompletedProcess([], 0, "https://127.0.0.1:8443", ""),
        ]
    )
    monkeypatch.setattr(cloud_operation_gate, "_run", lambda *args: next(responses))
    result = cloud_operation_gate.verify_minikube_context("feature-test")
    assert result == ContextVerification(True, True, "feature-test")


def test_verified_wrapper_inspects_scripts_in_any_directory(tmp_path: Path) -> None:
    verify = lambda context: ContextVerification(True, True, "feature-test")
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    for script in (notes / "seed.sh", tmp_path / "seed.sh"):
        script.write_text(
            "#!/bin/sh\nkubectl --context feature-test delete deployment api\n",
            encoding="utf-8",
        )
        command = (
            f"{Path.home()}/.ralph-codex/bin/run-local-minikube-script "
            f"--profile feature-test --context feature-test {script}"
        )
        assessment = assess_command(command, tmp_path, verify)
        assert assessment.action == "allow"
        assert assessment.profile == "feature-test"


def test_script_approval_changes_when_script_content_changes(tmp_path: Path) -> None:
    script = tmp_path / "cloud.sh"
    script.write_text("#!/bin/sh\naws s3 cp one s3://bucket/one\n", encoding="utf-8")
    first = assess_command(f"bash {script}", tmp_path)
    script.write_text("#!/bin/sh\naws s3 cp two s3://bucket/two\n", encoding="utf-8")
    second = assess_command(f"bash {script}", tmp_path)
    assert first.action == "approval"
    assert second.action == "approval"
    assert first.approval_subject != second.approval_subject


def test_script_kubectl_without_context_is_blocked_in_any_directory(tmp_path: Path) -> None:
    script = tmp_path / "cluster.sh"
    script.write_text("#!/bin/sh\nkubectl get pods\n", encoding="utf-8")
    assessment = assess_command(f"bash {script}", tmp_path)
    assert assessment.reason_code == "kubectl_context_required"


def test_minikube_wrapper_name_without_canonical_path_requires_approval(tmp_path: Path) -> None:
    command = "./run-local-minikube-script --profile feature-test --context feature-test .local-notes/seed.sh"
    payload = json.loads(run_guard(tmp_path, command, tmp_path / "approvals").stdout)
    assert payload["reason_code"] == "cloud_command_approval_required"
    assert payload["tool"] == "local-script"


def load_runner():
    path = ROOT / "scripts" / "security" / "run-local-minikube-script.py"
    spec = importlib.util.spec_from_file_location("run_local_minikube_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_rejects_endpoint_mismatch(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / ".local-notes"
    notes.mkdir()
    script = notes / "seed.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o700)
    runner = load_runner()
    outputs = iter(
        [
            json.dumps({"Host": "Running", "APIServer": "Running"}),
            "minikube-profile",
            "https://production.example",
            "https://127.0.0.1:8443",
        ]
    )
    monkeypatch.setattr(runner, "checked_output", lambda *args: next(outputs))
    monkeypatch.setattr(sys, "argv", ["runner", "--profile", "profile", "--context", "minikube-profile", str(script)])
    try:
        runner.main()
    except SystemExit as exc:
        assert "does not belong" in str(exc)
    else:
        raise AssertionError("endpoint mismatch must be refused")


def test_runner_accepts_regular_script_outside_local_notes(tmp_path: Path, monkeypatch, capsys) -> None:
    script = tmp_path / "seed.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o700)
    runner = load_runner()
    outputs = iter(
        [
            json.dumps({"Host": "Running", "APIServer": "Running"}),
            "feature-test",
            "https://127.0.0.1:8443",
            "https://127.0.0.1:8443",
            "apiVersion: v1",
        ]
    )
    monkeypatch.setattr(runner, "checked_output", lambda *args: next(outputs))
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0))
    monkeypatch.setattr(sys, "argv", ["runner", "--profile", "feature-test", "--context", "feature-test", str(script)])
    assert runner.main() == 0
    assert "MINIKUBE_CONTEXT_VERIFIED profile=feature-test context=feature-test" in capsys.readouterr().out
