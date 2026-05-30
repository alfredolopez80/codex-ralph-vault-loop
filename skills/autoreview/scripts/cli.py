from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from git_bundle import branch_bundle, changed_paths, choose_target, commit_bundle, current_branch, load_extra_files, local_bundle, repo_root
from review import build_prompt, extract_json, print_report, run_codex, validate_report
from safety import CLASSIFICATIONS, load_classifier, report_classification, report_findings


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
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def build_bundle(args: argparse.Namespace, repo: Path, target: str, target_ref: str | None) -> tuple[str, str | None]:
    if target == "local":
        return local_bundle(repo, include_untracked=args.include_untracked), target_ref
    if target == "branch":
        assert target_ref
        return branch_bundle(repo, target_ref, fetch=args.fetch), target_ref
    return commit_bundle(repo, args.commit), args.commit


def write_optional_outputs(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not args.output:
        print_report(report)
        return
    original_stdout = sys.stdout
    with Path(args.output).open("w", encoding="utf-8") as handle:
        sys.stdout = Tee(original_stdout, handle)
        print_report(report)
        sys.stdout = original_stdout


def start_parallel_tests(command: str, repo: Path) -> subprocess.Popen[str]:
    print(f"trusted parallel tests: {command}")
    return subprocess.Popen(command, cwd=repo, shell=True, text=True)


def main() -> int:
    args = parse_args()
    repo = repo_root()
    target, target_ref = choose_target(repo, args.mode, args.base)
    classifier = load_classifier(repo)

    if args.web_search and args.sensitivity != "GREEN":
        raise SystemExit("--web-search requires --sensitivity GREEN")
    if args.sensitivity == "RED":
        raise SystemExit("refusing reviewer execution for requested RED sensitivity")

    bundle, target_ref = build_bundle(args, repo, target, target_ref)
    reviewed_paths = changed_paths(repo, target, target_ref, args.commit, include_untracked=args.include_untracked)
    extra_prompt = "\n\n".join(args.prompt or [])
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
    if args.dry_run:
        return 0

    tests_proc: subprocess.Popen[str] | None = None
    if args.parallel_tests:
        tests_proc = start_parallel_tests(args.parallel_tests, repo)
    try:
        raw = run_codex(args, repo, prompt)
        report = extract_json(raw)
        validate_report(report, reviewed_paths, strict_changed_paths=args.strict_changed_paths)
        write_optional_outputs(args, report)
    finally:
        tests_status = tests_proc.wait() if tests_proc is not None else 0
        if tests_proc is not None:
            print(f"tests exit: {tests_status}")
    return 1 if tests_status != 0 or report["findings"] or report["overall_correctness"] == "patch is incorrect" else 0


def print_status(args: argparse.Namespace, repo: Path, target: str, classification: str, findings: list[dict[str, str]], prompt_len: int) -> None:
    print(f"autoreview target: {target}")
    print(f"branch: {current_branch(repo)}")
    print(f"engine: {args.engine}")
    print(f"web_search: {'on' if args.web_search else 'off'}")
    print(f"fetch: {'on' if args.fetch else 'off'}")
    print(f"include_untracked: {'on' if args.include_untracked else 'off'}")
    print(f"safety: {classification}")
    if findings:
        print(f"safety_findings: {json.dumps(findings, sort_keys=True)}")
    print(f"bundle: {prompt_len} chars")


class Tee:
    def __init__(self, *streams: Any) -> None:
        self.streams = streams

    def write(self, data: str) -> None:
        for stream in self.streams:
            stream.write(data)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()
