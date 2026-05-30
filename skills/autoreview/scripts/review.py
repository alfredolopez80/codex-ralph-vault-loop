from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any


MAX_OVERALL_EXPLANATION = 3200
STRICT_CHANGED_PATHS_NOTE = "All findings were outside the changed path set under --strict-changed-paths."


SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings", "overall_correctness", "overall_explanation", "overall_confidence"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "body", "priority", "confidence", "category", "code_location"],
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 140},
                    "body": {"type": "string", "minLength": 1, "maxLength": 2200},
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "category": {"type": "string", "enum": ["bug", "security", "regression", "test_gap", "maintainability"]},
                    "code_location": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["file_path", "line"],
                        "properties": {"file_path": {"type": "string", "minLength": 1}, "line": {"type": "integer", "minimum": 1}},
                    },
                },
            },
        },
        "overall_correctness": {"type": "string", "enum": ["patch is correct", "patch is incorrect"]},
        "overall_explanation": {"type": "string", "minLength": 1, "maxLength": MAX_OVERALL_EXPLANATION},
        "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def build_prompt(repo: Path, target: str, target_ref: str | None, bundle: str, extra_prompt: str, extra_files: str) -> str:
    target_line = f"{target} {target_ref}" if target_ref else target
    repo_label = repo.name or "repository"
    return textwrap.dedent(
        f"""
        You are a senior code reviewer. Review the provided git change bundle only.

        Hard rules:
        - Return exactly one JSON object and nothing else.
        - The JSON object must match this schema exactly:
        {json.dumps(SCHEMA, indent=2)}
        - Do not modify files.
        - Do not invoke nested reviewers or review tools.
        - Do not inspect the filesystem. The reviewer workspace is intentionally empty and the authoritative input is the bundle below.
        - Shell commands, if available, must be read-only inspection commands.
        - Do not run tests, formatters, package installs, generators, network mutation commands, git mutation commands, or commands that write files.
        - Report only actionable defects introduced or exposed by this change.
        - Include concrete security findings when the diff weakens a trust boundary.
        - Findings may point to unchanged supporting files when the changed code causally weakens or reaches that location. Explain the causal link in the finding body.
        - Prefer the root cause line when it is in the changed patch.
        - If there are no actionable findings, return an empty findings array and mark the patch correct.

        Review target: {target_line}
        Repository label: {repo_label}
        Reviewer workspace: sanitized temporary directory; no target checkout is mounted.

        {extra_prompt}

        {extra_files}

        # Change Bundle
        {bundle}
        """
    ).strip()


def run_codex(args: argparse.Namespace, repo: Path, prompt: str) -> str:
    with tempfile.TemporaryDirectory(prefix="autoreview-codex-") as workspace:
        review_root = Path(workspace)
        schema_path = write_json_temp(SCHEMA, directory=review_root)
        output_path = review_root / "last-message.json"
        output_path.write_text("", encoding="utf-8")
        cmd = [
            args.codex_bin,
            "--ask-for-approval",
            "never",
        ]
        if args.web_search:
            cmd.append("--search")
        if args.model:
            cmd.extend(["--model", args.model])
        cmd.extend(
            [
                "exec",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--ephemeral",
                "-C",
                str(review_root),
                "-s",
                "read-only",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ]
        )
        result = run_with_heartbeat(cmd, review_root, input_text=prompt, label="codex", env=sanitized_codex_env())
        output = output_path.read_text(encoding="utf-8")
        if result.returncode != 0:
            raise SystemExit(f"codex engine failed ({result.returncode})\n{result.stderr or result.stdout}")
        return output or result.stdout


def sanitized_codex_env() -> dict[str, str]:
    allowed = {"CODEX_HOME", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "LOGNAME", "PATH", "SHELL", "TERM", "TMPDIR", "USER"}
    return {key: value for key, value in os.environ.items() if key in allowed}


def write_json_temp(data: dict[str, Any], *, directory: Path | None = None) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=directory)
    with handle:
        json.dump(data, handle)
    return Path(handle.name)


def run_with_heartbeat(
    args: list[str],
    cwd: Path,
    *,
    input_text: str | None,
    label: str,
    heartbeat_seconds: float = 60,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pending_input = input_text
    while True:
        try:
            stdout, stderr = proc.communicate(input=pending_input, timeout=heartbeat_seconds)
            return subprocess.CompletedProcess(args, int(proc.returncode or 0), stdout, stderr)
        except subprocess.TimeoutExpired:
            elapsed = int(time.monotonic() - started)
            print(f"review still running: {label} elapsed={elapsed}s pid={proc.pid}", file=sys.stderr, flush=True)
            pending_input = None


def extract_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise SystemExit("review output did not contain a JSON object")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise SystemExit("review JSON must be an object")
    return parsed


def validate_report(report: dict[str, Any], reviewed_paths: set[str], *, strict_changed_paths: bool) -> None:
    allowed_top = {"findings", "overall_correctness", "overall_explanation", "overall_confidence"}
    extra_top = set(report) - allowed_top
    if extra_top:
        raise SystemExit(f"review JSON has unexpected top-level keys: {sorted(extra_top)}")
    for key in SCHEMA["required"]:
        if key not in report:
            raise SystemExit(f"review JSON missing required key: {key}")
    if not isinstance(report["findings"], list):
        raise SystemExit("review JSON findings must be an array")
    if report["overall_correctness"] not in {"patch is correct", "patch is incorrect"}:
        raise SystemExit("review JSON has invalid overall_correctness")
    validate_string(
        "review JSON overall_explanation",
        report["overall_explanation"],
        min_length=1,
        max_length=MAX_OVERALL_EXPLANATION,
    )
    if not number_in_range(report["overall_confidence"]):
        raise SystemExit("review JSON overall_confidence must be numeric")
    filter_findings(report, reviewed_paths, strict_changed_paths=strict_changed_paths)


def filter_findings(report: dict[str, Any], reviewed_paths: set[str], *, strict_changed_paths: bool) -> None:
    kept: list[dict[str, Any]] = []
    outside: list[str] = []
    for index, finding in enumerate(report["findings"]):
        validate_finding(index, finding)
        rel = finding["code_location"]["file_path"]
        if rel not in reviewed_paths:
            outside.append(f"{rel}:{finding['code_location']['line']}")
            if strict_changed_paths:
                continue
        kept.append(finding)
    if outside:
        print("autoreview preserved supporting finding locations: " + ", ".join(outside), file=sys.stderr)
    if strict_changed_paths and len(kept) != len(report["findings"]):
        report["findings"] = kept
        if not kept and report["overall_correctness"] == "patch is incorrect":
            report["overall_correctness"] = "patch is correct"
            report["overall_explanation"] = append_schema_bounded_note(
                report["overall_explanation"],
                STRICT_CHANGED_PATHS_NOTE,
                max_length=MAX_OVERALL_EXPLANATION,
            )


def validate_finding(index: int, finding: Any) -> None:
    if not isinstance(finding, dict):
        raise SystemExit(f"finding {index} must be an object")
    allowed = {"title", "body", "priority", "confidence", "category", "code_location"}
    extra = set(finding) - allowed
    if extra:
        raise SystemExit(f"finding {index} has unexpected keys: {sorted(extra)}")
    for key in allowed:
        if key not in finding:
            raise SystemExit(f"finding {index} missing required key: {key}")
    validate_string(f"finding {index} title", finding["title"], min_length=1, max_length=140)
    validate_string(f"finding {index} body", finding["body"], min_length=1, max_length=2200)
    if finding["priority"] not in {"P0", "P1", "P2", "P3"}:
        raise SystemExit(f"finding {index} has invalid priority")
    if finding["category"] not in {"bug", "security", "regression", "test_gap", "maintainability"}:
        raise SystemExit(f"finding {index} has invalid category")
    if not number_in_range(finding["confidence"]):
        raise SystemExit(f"finding {index} has invalid confidence")
    validate_location(index, finding["code_location"])


def validate_location(index: int, location: Any) -> None:
    if not isinstance(location, dict):
        raise SystemExit(f"finding {index} missing code_location")
    allowed = {"file_path", "line"}
    extra = set(location) - allowed
    if extra:
        raise SystemExit(f"finding {index} code_location has unexpected keys: {sorted(extra)}")
    for key in allowed:
        if key not in location:
            raise SystemExit(f"finding {index} code_location missing required key: {key}")
    if not isinstance(location["file_path"], str):
        raise SystemExit(f"finding {index} has invalid file path")
    rel = location["file_path"].strip()
    line = location.get("line")
    if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise SystemExit(f"finding {index} uses invalid file path: {rel}")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        raise SystemExit(f"finding {index} has invalid line")


def validate_string(name: str, value: Any, *, min_length: int, max_length: int) -> None:
    if not isinstance(value, str) or len(value) < min_length or len(value) > max_length:
        raise SystemExit(f"{name} must be a string with length {min_length}..{max_length}")


def append_schema_bounded_note(text: str, note: str, *, max_length: int) -> str:
    suffix = f"\n\n{note}"
    if len(text) + len(suffix) <= max_length:
        return text + suffix
    return note


def number_in_range(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def print_report(report: dict[str, Any]) -> None:
    findings = report["findings"]
    if findings:
        print(f"autoreview findings: {len(findings)}")
    elif report["overall_correctness"] == "patch is incorrect":
        print("autoreview verdict: patch is incorrect without discrete findings")
    else:
        print("autoreview clean: no accepted/actionable findings reported")
    for finding in findings:
        loc = finding["code_location"]
        print(f"[{finding['priority']}] {finding['title']}")
        print(f"{loc['file_path']}:{loc['line']}")
        print(finding["body"])
        print()
    print(f"overall: {report['overall_correctness']} ({report['overall_confidence']})")
    print(report["overall_explanation"])
