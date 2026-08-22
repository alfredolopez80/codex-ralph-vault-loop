from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".codex" / "hooks"))

from shared.cloud_operation_gate import CommandAssessment, ContextVerification, assess_command


def verified_minikube(context: str, kubeconfig: str = "") -> ContextVerification:
    return ContextVerification(True, True, "feature-test")


def decision_summary(assessment: CommandAssessment) -> tuple[str, ...]:
    return (
        assessment.action,
        assessment.reason_code,
        assessment.risk_level,
        assessment.tool,
        assessment.consequence,
    )


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
    assert aws.action == "block"
    assert aws.reason_code == "cloud_destructive_command_blocked"
    assert kubectl.reason_code == "kubectl_context_required"


def test_script_rewrite_before_execution_requires_approval(tmp_path: Path) -> None:
    script = tmp_path / "seed.sh"
    script.write_text("#!/bin/sh\necho safe\n", encoding="utf-8")
    command = f"printf replacement > {script}; bash {script}"
    assessment = assess_command(command, tmp_path)
    assert assessment.action == "approval"
    assert "rewrite" in assessment.consequence


def test_shell_noexec_skips_command_text_cloud_execution(tmp_path: Path) -> None:
    commands = (
        "bash -n -c 'aws s3 cp artifact s3://bucket/artifact'",
        "bash -nc 'aws s3 cp artifact s3://bucket/artifact'",
        "bash -o noexec -c 'aws s3 cp artifact s3://bucket/artifact'",
    )

    for command in commands:
        assert assess_command(command, tmp_path).action == "allow", command


def test_shell_noexec_can_be_reenabled_before_command_text(tmp_path: Path) -> None:
    assessment = assess_command(
        "bash -n +n -c 'aws s3 cp artifact s3://bucket/artifact'",
        tmp_path,
    )

    assert assessment.action == "approval"
    assert assessment.tool == "aws"


def test_shell_value_option_does_not_hide_executed_script(tmp_path: Path) -> None:
    script = tmp_path / "deploy.sh"
    script.write_text("aws s3 cp artifact s3://bucket/artifact\n", encoding="utf-8")

    executed = assess_command(f"bash -O extglob {script}", tmp_path)
    syntax_only = assess_command(f"bash -O extglob -n {script}", tmp_path)

    assert executed.action == "approval"
    assert syntax_only.action == "allow"


def test_python_option_values_do_not_hide_script_path(tmp_path: Path) -> None:
    script = tmp_path / "deploy.py"
    script.write_text("aws s3 cp artifact s3://bucket/artifact\n", encoding="utf-8")
    assessment = assess_command(f"python3 -W ignore {script}", tmp_path)
    assert assessment.action == "approval"


def test_python_fixture_text_is_not_treated_as_process_execution(tmp_path: Path) -> None:
    script = tmp_path / "fixture_check.py"
    script.write_text(
        'fixture = "aws ec2 terminate-instances --instance-ids i-example"\nprint(fixture)\n',
        encoding="utf-8",
    )

    assessment = assess_command(f"python3 {script}", tmp_path)

    assert assessment.action == "allow"


def test_python_subprocess_cloud_destruction_remains_blocked(tmp_path: Path) -> None:
    script = tmp_path / "deploy.py"
    script.write_text(
        "import subprocess\n"
        'command = ["aws", "ec2", "terminate-instances", "--instance-ids", "i-example"]\n'
        "subprocess.run(command, check=True)\n",
        encoding="utf-8",
    )

    assessment = assess_command(f"python3 {script}", tmp_path)

    assert assessment.action == "block"
    assert assessment.reason_code == "cloud_destructive_command_blocked"
    assert assessment.tool == "aws"


def test_python_local_command_builder_is_resolved_before_approval(tmp_path: Path) -> None:
    script = tmp_path / "dynamic-deploy.py"
    script.write_text(
        "import subprocess\n"
        "def build():\n"
        '    return ["aws", "s3", "cp", "artifact", "s3://bucket/artifact"]\n'
        "subprocess.run(build(), check=True)\n",
        encoding="utf-8",
    )

    assessment = assess_command(f"python3 {script}", tmp_path)

    assert assessment.action == "approval"
    assert assessment.tool == "aws"


def test_type_name_namespace_delete_is_complete(tmp_path: Path) -> None:
    assessment = assess_command(
        "kubectl --context feature-test delete namespace/feature-test",
        tmp_path,
        verified_minikube,
    )
    assert assessment.action == "block"
    assert assessment.reason_code == "cloud_destructive_command_blocked"
    assert assessment.risk_level == "destructive"


def test_newline_splits_shell_commands(tmp_path: Path) -> None:
    command = "echo ok\naws ec2 terminate-instances --instance-ids i-example"
    assessment = assess_command(command, tmp_path)
    assert assessment.action == "block"
    assert assessment.reason_code == "cloud_destructive_command_blocked"
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
    assert assessment.action == "block"
    assert assessment.reason_code == "cloud_destructive_command_blocked"
    assert assessment.tool == "aws"


def test_literal_cloud_tool_search_in_diagnostic_script_is_not_execution(tmp_path: Path) -> None:
    script = tmp_path / "doctor.sh"
    script.write_text(
        "#!/bin/sh\n"
        'grep -q "Require explicit \\`--context\\` on every \\`kubectl\\` command" policy.md\n',
        encoding="utf-8",
    )

    assessment = assess_command(f"bash {script}", tmp_path)

    assert assessment.action == "allow"


def test_shell_cloud_words_outside_command_position_are_not_execution(tmp_path: Path) -> None:
    script = tmp_path / "cluster-free-test.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'LOG_FILE="${TMP_DIR}/kubectl.log"\n'
        'python3 "${ROOT}/scripts/minikube/discover.py"\n'
        'cat >"${TMP_DIR}/kubectl" <<\'SH\'\n'
        "#!/usr/bin/env bash\n"
        "echo fake client\n"
        "SH\n"
        'echo "unexpected kubectl invocation" >&2\n'
        'chmod +x "${TMP_DIR}/kubectl"\n'
        'if run_sync env TEST_MODE=fake bash "${ROOT}/scripts/minikube/sync.sh" --context fake; then\n'
        "  echo passed\n"
        "fi\n"
        'if [[ "$(grep -c expected "${ROOT}/scripts/minikube/full-setup.sh")" -lt 2 ]]; then\n'
        "  echo missing fixture >&2\n"
        "fi\n",
        encoding="utf-8",
    )

    assessment = assess_command(f"bash {script}", tmp_path)

    assert assessment.action == "allow"


def test_ambiguous_shell_cloud_data_flow_requests_approval(tmp_path: Path) -> None:
    script = tmp_path / "ambiguous-cloud-data.sh"
    script.write_text(
        'for file in "${ROOT}/scripts/minikube/shim/kubectl"; do\n'
        '  test -f "${file}"\n'
        "done\n",
        encoding="utf-8",
    )

    assessment = assess_command(f"bash {script}", tmp_path)

    assert assessment.action == "approval"
    assert assessment.tool == "local-script"


def test_real_cloud_command_inside_generated_shell_body_remains_gated(tmp_path: Path) -> None:
    script = tmp_path / "generated-cloud-client.sh"
    script.write_text(
        'cat >"${TMP_DIR}/kubectl" <<\'SH\'\n'
        "#!/usr/bin/env bash\n"
        "/usr/bin/kubectl get pods\n"
        "SH\n",
        encoding="utf-8",
    )

    assessment = assess_command(f"bash {script}", tmp_path)

    assert assessment.action == "block", decision_summary(assessment)
    assert assessment.reason_code == "kubectl_context_required", decision_summary(assessment)


def test_real_shell_cloud_commands_still_require_their_normal_gate(tmp_path: Path) -> None:
    def non_minikube(context: str, kubeconfig: str = "") -> ContextVerification:
        return ContextVerification(True, False)

    for index, body in enumerate(
        (
            "kubectl --context production patch deployment api --patch '{}'\n",
            "bash -c 'kubectl --context production patch deployment api --patch {}'\n",
        )
    ):
        script = tmp_path / f"real-cloud-{index}.sh"
        script.write_text(body, encoding="utf-8")

        assessment = assess_command(f"bash {script}", tmp_path, non_minikube)

        assert assessment.action == "approval"
        assert assessment.tool == "kubectl"


def test_command_substitution_inside_search_literal_remains_gated(tmp_path: Path) -> None:
    script = tmp_path / "unsafe-doctor.sh"
    script.write_text(
        "#!/bin/sh\n"
        'grep -q "$(kubectl delete namespace production)" policy.md\n',
        encoding="utf-8",
    )

    assessment = assess_command(f"bash {script}", tmp_path)

    assert assessment.action == "block"
    assert assessment.reason_code == "kubectl_context_required"


def test_backtick_substitution_inside_search_literal_remains_gated(tmp_path: Path) -> None:
    script = tmp_path / "unsafe-backtick-doctor.sh"
    script.write_text(
        "#!/bin/sh\n"
        'grep -q "`kubectl delete namespace production`" policy.md\n',
        encoding="utf-8",
    )

    assessment = assess_command(f"bash {script}", tmp_path)

    assert assessment.action == "block"
    assert assessment.reason_code == "kubectl_context_required"


def test_shell_lexical_and_known_wrapper_forms_preserve_the_kubectl_gate(tmp_path: Path) -> None:
    bodies = (
        "kube''ctl delete namespace production\n",
        "kube\\ctl delete namespace production\n",
        "env -S 'kubectl delete namespace production'\n",
        "eval '/usr/bin/kubectl delete namespace production'\n",
        "bash -c 'exec /usr/bin/kubectl delete namespace production'\n",
        "bash -c 'command kubectl delete namespace production'\n",
    )

    for index, body in enumerate(bodies):
        script = tmp_path / f"known-wrapper-{index}.sh"
        script.write_text(body, encoding="utf-8")

        assessment = assess_command(f"bash {script}", tmp_path)

        assert assessment.action == "block", (body, decision_summary(assessment))
        assert assessment.reason_code == "kubectl_context_required", (body, decision_summary(assessment))


def test_dynamic_shell_cloud_data_requests_approval_instead_of_passing(tmp_path: Path) -> None:
    bodies = (
        'tool=kubectl\n"$tool" delete namespace production\n',
        "printf kubectl | xargs -I{} sh -c '{} delete namespace production'\n",
    )

    for index, body in enumerate(bodies):
        script = tmp_path / f"dynamic-wrapper-{index}.sh"
        script.write_text(body, encoding="utf-8")

        assessment = assess_command(f"bash {script}", tmp_path)

        assert assessment.action == "approval", body
        assert assessment.tool == "local-script", body


def test_inline_shell_wrappers_follow_the_same_block_or_approval_contract(tmp_path: Path) -> None:
    blocked = (
        "env -S 'kubectl delete namespace production'",
        "eval '/usr/bin/kubectl delete namespace production'",
        "bash -c 'exec /usr/bin/kubectl delete namespace production'",
        "bash -c 'command kubectl delete namespace production'",
    )
    ambiguous = (
        'tool=kubectl; "$tool" delete namespace production',
        'echo "kubectl delete namespace production" | sh',
    )

    for command in blocked:
        assessment = assess_command(command, tmp_path)
        assert assessment.action == "block", (command, decision_summary(assessment))
        assert assessment.reason_code == "kubectl_context_required", (command, decision_summary(assessment))
    for command in ambiguous:
        assessment = assess_command(command, tmp_path)
        assert assessment.action == "approval", command
        assert assessment.tool == "local-script", command


def test_non_shell_cloud_execution_is_never_misclassified_as_harmless(tmp_path: Path) -> None:
    scripts = {
        "deploy.js": 'require("child_process").execSync("kubectl delete namespace production")\n',
        "deploy.rb": 'system("aws s3 rm s3://bucket --recursive")\n',
        "deploy.pl": 'system("terraform destroy -auto-approve");\n',
    }

    for name, body in scripts.items():
        script = tmp_path / name
        script.write_text(body, encoding="utf-8")

        assessment = assess_command(f"{script}", tmp_path)

        assert assessment.action == "approval", name
