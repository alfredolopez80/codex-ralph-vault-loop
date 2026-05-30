from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any


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
        "overall_explanation": {"type": "string", "minLength": 1, "maxLength": 3200},
        "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def build_prompt(repo: Path, target: str, target_ref: str | None, bundle: str, extra_prompt: str, extra_files: str) -> str:
    target_line = f"{target} {target_ref}" if target_ref else target
    return textwrap.dedent(
        f"""
        You are a senior code reviewer. Review the provided git change bundle only.

        Hard rules:
        - Return exactly one JSON object and nothing else.
        - The JSON object must match this schema exactly:
        {json.dumps(SCHEMA, indent=2)}
        - Do not modify files.
        - Do not invoke nested reviewers or review tools.
        - Shell commands, if available, must be read-only inspection commands.
        - Do not run tests, formatters, package installs, generators, network mutation commands, git mutation commands, or commands that write files.
        - Report only actionable defects introduced or exposed by this change.
        - Include concrete security findings when the diff weakens a trust boundary.
        - Findings may point to unchanged supporting files when the changed code causally weakens or reaches that location. Explain the causal link in the finding body.
        - Prefer the root cause line when it is in the changed patch.
        - If there are no actionable findings, return an empty findings array and mark the patch correct.

        Review target: {target_line}
        Repository: {repo}

        {extra_prompt}

        {extra_files}

        # Change Bundle
        {bundle}
        """
    ).strip()


def run_codex(args: argparse.Namespace, repo: Path, prompt: str) -> str:
    schema_path = write_json_temp(SCHEMA)
    output_path = Path(tempfile.NamedTemporaryFile("w", suffix=".json", delete=False).name)
    cmd = [args.codex_bin, "--ask-for-approval", "never"]
    if args.web_search:
        cmd.append("--search")
    if args.model:
        cmd.extend(["--model", args.model])
    cmd.extend(["exec", "--ephemeral", "-C", str(repo), "-s", "read-only", "--output-schema", str(schema_path), "--output-last-message", str(output_path), "-"])
    result = run_with_heartbeat(cmd, repo, input_text=prompt, label="codex")
    try:
        output = output_path.read_text()
    finally:
        schema_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise SystemExit(f"codex engine failed ({result.returncode})\n{result.stderr or result.stdout}")
    return output or result.stdout


def write_json_temp(data: dict[str, Any]) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    with handle:
        json.dump(data, handle)
    return Path(handle.name)


def run_with_heartbeat(args: list[str], cwd: Path, *, input_text: str, label: str) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    proc = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    while True:
        try:
            stdout, stderr = proc.communicate(input=input_text, timeout=60)
            return subprocess.CompletedProcess(args, int(proc.returncode or 0), stdout, stderr)
        except subprocess.TimeoutExpired:
            elapsed = int(time.monotonic() - started)
            print(f"review still running: {label} elapsed={elapsed}s pid={proc.pid}", file=sys.stderr, flush=True)
            input_text = ""


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
    if not isinstance(report["overall_explanation"], str) or not report["overall_explanation"]:
        raise SystemExit("review JSON overall_explanation must be a non-empty string")
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
            report["overall_explanation"] += "\n\nAll findings were outside the changed path set under --strict-changed-paths."


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
    if not isinstance(finding["title"], str) or not finding["title"] or len(finding["title"]) > 140:
        raise SystemExit(f"finding {index} has invalid title")
    if not isinstance(finding["body"], str) or not finding["body"] or len(finding["body"]) > 2200:
        raise SystemExit(f"finding {index} has invalid body")
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
    rel = str(location.get("file_path", "")).strip()
    line = location.get("line")
    if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise SystemExit(f"finding {index} uses invalid file path: {rel}")
    if not isinstance(line, int) or line < 1:
        raise SystemExit(f"finding {index} has invalid line")


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
