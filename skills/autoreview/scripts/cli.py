from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from git_bundle import branch_bundle, changed_paths, choose_target, commit_bundle, current_branch, fetch_origin, load_extra_files, local_bundle, repo_root
from review import build_prompt, extract_json, print_report, run_codex, validate_report
from safety import CLASSIFICATIONS, load_classifier, report_classification, report_findings, resolve_safe_repo_output, sensitive_path_matches


ENGINES = ("codex",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ralph-safe bundle-driven AI code review.")
    parser.add_argument("--mode", choices=["auto", "local", "branch", "commit"], default="auto")
    parser.add_argument("--base")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--engine", choices=ENGINES, default=os.environ.get("AUTOREVIEW_ENGINE", "codex"))
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--model")
    parser.add_argument("--sensitivity", choices=CLASSIFICATIONS, default=os.environ.get("AUTOREVIEW_SENSITIVITY", "YELLOW"))
    parser.add_argument("--web-search", action="store_true", help="Allow reviewer web search. Requires --sensitivity GREEN.")
    parser.add_argument("--fetch", action="store_true", help="Fetch origin before branch diff.")
    parser.add_argument("--include-untracked", action="store_true", help="Include untracked non-ignored files after safety scan.")
    parser.add_argument("--strict-changed-paths", action="store_true", help="Drop findings outside changed paths.")
    parser.add_argument("--prompt", action="append")
    parser.add_argument("--prompt-file", action="append")
    parser.add_argument("--dataset", action="append")
    parser.add_argument("--output")
    parser.add_argument("--json-output")
    parser.add_argument("--parallel-tests", help="Trusted operator-supplied shell command to run concurrently.")
    parser.add_argument("--review-pass", type=int, choices=[1, 2], help="Bounded pass number. Pass 1 discovers; pass 2 is final closure.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def build_bundle(args: argparse.Namespace, repo: Path, target: str, target_ref: str | None) -> tuple[str, str | None]:
    if target == "local":
        return local_bundle(repo, include_untracked=args.include_untracked), target_ref
    if target == "branch":
        assert target_ref
        return branch_bundle(repo, target_ref, fetch=False), target_ref
    return commit_bundle(repo, args.commit), args.commit


def write_optional_outputs(args: argparse.Namespace, repo: Path, report: dict[str, Any]) -> None:
    json_text = json.dumps(report, indent=2) + "\n"
    if args.json_output:
        resolve_safe_repo_output(repo, args.json_output, context="json-output").write_text(json_text, encoding="utf-8")
    if args.output:
        resolve_safe_repo_output(repo, args.output, context="output").write_text(human_report_text(report), encoding="utf-8")
    sys.stdout.write(json_text)


def human_report_text(report: dict[str, Any]) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print_report(report)
    return buffer.getvalue()


def start_parallel_tests(command: str, repo: Path) -> subprocess.Popen[str]:
    log = tempfile.NamedTemporaryFile("w", prefix="autoreview-tests.", suffix=".log", delete=False)
    print(f"trusted parallel tests: {command} log={log.name}", file=sys.stderr)
    proc = subprocess.Popen(command, cwd=repo, shell=True, text=True, stdout=log, stderr=subprocess.STDOUT)
    proc.autoreview_log_path = log.name  # type: ignore[attr-defined]
    log.close()
    return proc


def main() -> int:
    args = parse_args()
    if not args.dry_run and args.review_pass is None:
        raise SystemExit("autoreview execution requires --review-pass 1 or --review-pass 2; do not rerun indefinitely")
    repo = repo_root()
    target, target_ref = choose_target(repo, args.mode, args.base)
    classifier = load_classifier(repo)

    if args.web_search and args.sensitivity != "GREEN":
        raise SystemExit("--web-search requires --sensitivity GREEN")
    if args.sensitivity == "RED":
        raise SystemExit("refusing reviewer execution for requested RED sensitivity")
    if target == "branch" and args.fetch:
        fetch_origin(repo)

    reviewed_paths = changed_paths(repo, target, target_ref, args.commit, include_untracked=args.include_untracked)
    sensitive_paths = sensitive_path_matches(reviewed_paths)
    if sensitive_paths:
        raise SystemExit("refusing review with sensitive changed paths: " + ", ".join(sensitive_paths))
    bundle, target_ref = build_bundle(args, repo, target, target_ref)
    prompt_chunks = [bounded_review_instructions(args.review_pass), *(args.prompt or [])]
    extra_prompt = "\n\n".join(chunk for chunk in prompt_chunks if chunk)
    extra_files = "\n\n".join(
        chunk
        for chunk in (
            load_extra_files(repo, args.prompt_file, label="prompt-file"),
            load_extra_files(repo, args.dataset, label="dataset"),
        )
        if chunk
    )
    prompt = build_prompt(repo, target, target_ref, bundle, extra_prompt, extra_files)
    safety = classifier(prompt, args.sensitivity)
    classification = report_classification(safety)
    print_status(args, repo, target, classification, report_findings(safety), len(prompt))
    if classification == "RED":
        raise SystemExit("refusing reviewer execution because bundle contains sensitive material")
    if args.web_search and classification != "GREEN":
        raise SystemExit("refusing web search because classified bundle is not GREEN")
    if args.dry_run:
        return 0

    tests_proc: subprocess.Popen[str] | None = None
    if args.parallel_tests:
        tests_proc = start_parallel_tests(args.parallel_tests, repo)
    report: dict[str, Any] | None = None
    primary_error: BaseException | None = None
    tests_status = 0
    tests_log_path: str | None = None
    try:
        raw = run_codex(args, repo, prompt)
        candidate_report = extract_json(raw)
        validate_report(candidate_report, reviewed_paths, strict_changed_paths=args.strict_changed_paths)
        write_optional_outputs(args, repo, candidate_report)
        report = candidate_report
    except (Exception, SystemExit) as exc:
        primary_error = exc
    finally:
        tests_status = tests_proc.wait() if tests_proc is not None else 0
        if tests_proc is not None:
            tests_log_path = getattr(tests_proc, "autoreview_log_path", "<unknown>")
            print(f"tests exit: {tests_status} log={tests_log_path}", file=sys.stderr)
    if primary_error is not None:
        if tests_status != 0:
            raise SystemExit(f"{primary_error}\nparallel tests failed ({tests_status}) log={tests_log_path}")
        raise primary_error
    if report is None:
        raise SystemExit("autoreview did not produce a validated report")
    return 1 if tests_status != 0 or report["findings"] or report["overall_correctness"] == "patch is incorrect" else 0


def print_status(args: argparse.Namespace, repo: Path, target: str, classification: str, findings: list[dict[str, str]], prompt_len: int) -> None:
    print(f"autoreview target: {target}", file=sys.stderr)
    print(f"branch: {current_branch(repo)}", file=sys.stderr)
    print(f"engine: {args.engine}", file=sys.stderr)
    print(f"review_pass: {args.review_pass if args.review_pass else 'unspecified'} of 2", file=sys.stderr)
    print(f"web_search: {'on' if args.web_search else 'off'}", file=sys.stderr)
    print(f"fetch: {'on' if args.fetch else 'off'}", file=sys.stderr)
    print(f"include_untracked: {'on' if args.include_untracked else 'off'}", file=sys.stderr)
    print(f"safety: {classification}", file=sys.stderr)
    if findings:
        print(f"safety_findings: {json.dumps(findings, sort_keys=True)}", file=sys.stderr)
    print(f"bundle: {prompt_len} chars", file=sys.stderr)


def bounded_review_instructions(review_pass: int | None) -> str:
    if review_pass == 1:
        return (
            "Bounded review protocol: this is review pass 1 of 2. "
            "Find all actionable defects in one integrated review instead of one finding per rerun. "
            "The operator will batch fixes from this pass before the final pass."
        )
    if review_pass == 2:
        return (
            "Bounded review protocol: this is review pass 2 of 2, the final closure pass. "
            "Report only unresolved issues or regressions introduced by the pass-1 fixes. "
            "After this pass, do not request another automatic autoreview run; residual findings must be reported for human decision."
        )
    return ""
