from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.cloud_operation_gate import ContextVerification, assess_command  # noqa: E402


def verified_minikube(context: str, kubeconfig: str = "") -> ContextVerification:
    return ContextVerification(True, True, "feature-test")


def test_alternate_kubeconfig_is_bound_to_context_verification(tmp_path: Path) -> None:
    seen: list[str] = []

    def verifier(context: str, kubeconfig: str = "") -> ContextVerification:
        seen.append(kubeconfig)
        return ContextVerification(True, not bool(kubeconfig), "feature-test" if not kubeconfig else "")

    explicit = assess_command(
        "kubectl --kubeconfig prod.yaml --context feature-test apply -f deployment.yaml",
        tmp_path,
        verifier,
    )
    environment = assess_command(
        "KUBECONFIG=prod.yaml kubectl --context feature-test apply -f deployment.yaml",
        tmp_path,
        verifier,
    )
    assert explicit.action == "approval"
    assert environment.action == "approval"
    assert seen == [str(tmp_path / "prod.yaml"), str(tmp_path / "prod.yaml")]


def test_env_options_do_not_hide_cloud_commands(tmp_path: Path) -> None:
    aws = assess_command("env -i AWS_PROFILE=prod aws ec2 terminate-instances --instance-ids i-example", tmp_path)
    kubectl = assess_command("env -u KUBECONFIG kubectl delete namespace prod", tmp_path)
    assert aws.action == "approval"
    assert kubectl.reason_code == "kubectl_context_required"


def test_script_rewrite_before_execution_requires_approval(tmp_path: Path) -> None:
    script = tmp_path / "seed.sh"
    script.write_text("#!/bin/sh\necho safe\n", encoding="utf-8")
    command = f"printf replacement > {script}; bash {script}"
    assessment = assess_command(command, tmp_path)
    assert assessment.action == "approval"
    assert "rewrite" in assessment.consequence


def test_python_option_values_do_not_hide_script_path(tmp_path: Path) -> None:
    script = tmp_path / "deploy.py"
    script.write_text("aws s3 cp artifact s3://bucket/artifact\n", encoding="utf-8")
    assessment = assess_command(f"python3 -W ignore {script}", tmp_path)
    assert assessment.action == "approval"


def test_type_name_namespace_delete_is_complete(tmp_path: Path) -> None:
    assessment = assess_command(
        "kubectl --context feature-test delete namespace/feature-test",
        tmp_path,
        verified_minikube,
    )
    assert assessment.action == "approval"
    assert assessment.risk_level == "destructive"


def test_newline_splits_shell_commands(tmp_path: Path) -> None:
    command = "echo ok\naws ec2 terminate-instances --instance-ids i-example"
    assessment = assess_command(command, tmp_path)
    assert assessment.action == "approval"
    assert assessment.tool == "aws"


def test_cd_updates_script_resolution(tmp_path: Path) -> None:
    directory = tmp_path / "dir"
    directory.mkdir()
    script = directory / "seed.sh"
    script.write_text("aws s3 cp artifact s3://bucket/artifact\n", encoding="utf-8")
    assessment = assess_command("cd dir && bash seed.sh", tmp_path)
    assert assessment.action == "approval"
    assert assessment.tool == "aws"


def test_slashless_cloud_tool_uses_path_not_cwd_file(tmp_path: Path) -> None:
    shadow = tmp_path / "aws"
    shadow.write_text("#!/bin/sh\necho harmless\n", encoding="utf-8")
    shadow.chmod(0o700)
    assessment = assess_command("aws ec2 terminate-instances --instance-ids i-example", tmp_path)
    assert assessment.action == "approval"
    assert assessment.tool == "aws"
