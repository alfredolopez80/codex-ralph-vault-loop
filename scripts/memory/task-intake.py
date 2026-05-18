#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "do",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "please",
    "the",
    "this",
    "to",
    "with",
    "you",
}
YELLOW_MARKERS = (
    "confidential",
    "internal",
    "not public",
    "private repo",
    "proprietary",
    "sanitized log",
    "sanitized trace",
)


@dataclass(frozen=True)
class Sensitivity:
    classification: str
    redacted_text: str
    changed: bool
    findings: tuple[str, ...]


def load_classifier():
    security_dir = REPO_ROOT / "scripts" / "security"
    if str(security_dir) not in sys.path:
        sys.path.insert(0, str(security_dir))
    try:
        from sensitive_content import classify_text  # type: ignore
    except Exception:
        return None
    return classify_text


def classify_prompt(prompt: str) -> Sensitivity:
    classifier = load_classifier()
    if classifier is None:
        classification = "YELLOW" if looks_yellow(prompt) else "GREEN"
        return Sensitivity(classification, prompt, False, ())
    report = classifier(prompt)
    classification = getattr(report, "classification", "GREEN")
    if classification == "GREEN" and looks_yellow(prompt):
        classification = "YELLOW"
    findings = tuple(getattr(finding, "label", "sensitive") for finding in getattr(report, "findings", ()))
    return Sensitivity(
        classification=classification,
        redacted_text=getattr(report, "redacted_text", ""),
        changed=bool(getattr(report, "changed", False)),
        findings=findings,
    )


def looks_yellow(prompt: str) -> bool:
    text = prompt.lower()
    return any(marker in text for marker in YELLOW_MARKERS)


def read_stdin_payload() -> dict[str, Any]:
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"prompt": raw}
    return data if isinstance(data, dict) else {}


def repo_basename() -> str:
    return REPO_ROOT.name


def safe_project(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or repo_basename()


def extract_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    payload = read_stdin_payload()
    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    return prompt if isinstance(prompt, str) else str(prompt)


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_./-]+", text.lower())


def task_type_for(prompt: str) -> str:
    text = prompt.lower()
    checks = (
        ("security", ("security", "secret", "credential", "private key", "wallet", "threat", "vulnerability")),
        ("code_review", ("review", "audit", "pr ", "pull request", "diff")),
        ("debugging", ("debug", "bug", "error", "fail", "failure", "broken", "traceback", "fix it")),
        ("logs", ("log", "trace", "stack", "stderr", "stdout")),
        ("tests", ("test", "playwright", "pytest", "unit", "e2e", "spec")),
        ("research", ("research", "look up", "investigate", "compare", "latest")),
        ("architecture", ("architecture", "design", "migration", "plan", "diagram", "system")),
        ("implementation", ("implement", "build", "create", "add", "update", "fix", "wire", "refactor")),
    )
    for task_type, needles in checks:
        if any(needle in text for needle in needles):
            return task_type
    return "other"


def is_vague(prompt: str) -> bool:
    stripped = prompt.strip().lower()
    token_count = len(words(stripped))
    vague_exact = {
        "fix it",
        "do it",
        "make it work",
        "continue",
        "go ahead",
        "help",
        "help me",
        "review this",
        "analyze this",
        "check this",
    }
    if stripped in vague_exact:
        return True
    if token_count <= 3 and re.search(r"\b(it|this|that|todo|eso|esto|arreglalo|fix|review|analyze|check)\b", stripped):
        return True
    if token_count <= 5 and stripped.startswith(("fix ", "do ", "review ", "analyze ", "check ", "update ")):
        concrete_markers = ("/", ".", "#", "pr ", "issue ", "file", "branch", "error", "test")
        return not any(marker in stripped for marker in concrete_markers)
    return False


def clarifying_questions(task_type: str) -> list[str]:
    common = [
        "What exact file, branch, PR, feature, or behavior should I work on?",
        "What outcome should count as done?",
        "What validation do you expect me to run before reporting back?",
    ]
    by_type = {
        "debugging": [
            "What error message, failing command, or reproduction path should I use?",
            "What changed recently that may have caused the failure?",
        ],
        "implementation": [
            "Should I make code changes now, or only inspect and plan first?",
            "Are there constraints on scope, compatibility, or tests?",
        ],
        "code_review": [
            "Which commit, diff, branch, or PR should I review?",
            "Should the review be chat-only or should I post comments anywhere?",
        ],
    }
    questions = by_type.get(task_type, []) + common
    return questions[:5]


def estimate_complexity(prompt: str, task_type: str, sensitivity: str, vague: bool) -> int:
    text = prompt.lower()
    score = 2
    if task_type in {"security", "architecture", "debugging"}:
        score += 3
    elif task_type in {"implementation", "code_review", "tests"}:
        score += 2
    if sensitivity == "RED":
        score += 2
    elif sensitivity == "YELLOW":
        score += 1
    if any(term in text for term in ("deep", "exhaustive", "migration", "hooks", "workflow", "multi-agent")):
        score += 1
    if any(term in text for term in ("production", "global", "security", "private key", "wallet", ".env")):
        score += 1
    if vague:
        score = min(score, 4)
    return max(1, min(score, 10))


def route_for(sensitivity: str, task_type: str, complexity: int, vague: bool) -> tuple[str, str]:
    if sensitivity == "RED":
        return "local", "RED content must stay local"
    if vague:
        return "local", "request is underspecified; clarify before action"
    if sensitivity == "YELLOW" and complexity >= 5:
        return "external-mcp", "YELLOW may use external MCP only after sanitization"
    if sensitivity == "GREEN" and task_type in {"research", "architecture", "security", "debugging", "code_review"} and 4 <= complexity <= 6:
        return "external-mcp", "sanitized advisory review may be useful"
    if complexity >= 7:
        return "codex-subagent", "complex local work may benefit from bounded Codex subagents"
    return "local", "local execution is sufficient"


def recall_query(redacted_prompt: str) -> str:
    normalized = re.sub(r"\[REDACTED:([A-Za-z0-9_-]+)\]", r" \1 ", redacted_prompt)
    selected: list[str] = []
    for term in words(normalized):
        term = term.strip("./-")
        if len(term) < 3 or term in STOPWORDS:
            continue
        if term not in selected:
            selected.append(term)
        if len(selected) >= 10:
            break
    return " ".join(selected)


def run_recall(query: str, project: str, limit: int, project_id: str = "", workspace_root: str = "") -> tuple[str, str]:
    if not query:
        return "skipped", ""
    recall = REPO_ROOT / "scripts" / "memory" / "ralph-recall.py"
    if not recall.exists():
        return "skipped", "recall script missing"
    command = [sys.executable, str(recall), query, "--project", project, "--limit", str(limit)]
    if project_id:
        command.extend(["--project-id", project_id])
    if workspace_root:
        command.extend(["--workspace-root", workspace_root])
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        return "failed", (result.stderr or result.stdout).strip()
    return "ran", result.stdout.strip()


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Ralph Task Intake",
        f"sensitivity={payload['sensitivity']}",
        f"complexity={payload['complexity']}",
        f"task_type={payload['task_type']}",
        f"route={payload['route']}",
        f"clarification_required={payload['clarification_required']}",
        f"CLARIFICATION_REQUIRED={payload['clarification_required']}",
        f"reason={payload['reason']}",
    ]
    if payload["clarification_required"] == "yes":
        lines.append("clarifying_questions=")
        for question in payload["clarifying_questions"]:
            lines.append(f"- {question}")
    lines.append(f"recall_status={payload['recall_status']}")
    if payload.get("project"):
        lines.append(f"PROJECT_SLUG={payload['project']}")
    if payload.get("project_id"):
        lines.append(f"PROJECT_ID={payload['project_id']}")
    if payload.get("workspace_root"):
        lines.append(f"WORKSPACE_ROOT={payload['workspace_root']}")
    if payload.get("recall_output"):
        lines.extend(["", str(payload["recall_output"]).strip()])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify a user prompt and run safe targeted Ralph recall.")
    parser.add_argument("--prompt")
    parser.add_argument("--project", default=repo_basename())
    parser.add_argument("--project-id", default=os.environ.get("RALPH_PROJECT_ID", ""))
    parser.add_argument("--workspace-root", default=os.environ.get("RALPH_WORKSPACE_ROOT", ""))
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-recall", action="store_true")
    args = parser.parse_args()

    prompt = extract_prompt(args).strip()
    project = safe_project(args.project)
    sensitivity = classify_prompt(prompt)
    task_type = task_type_for(sensitivity.redacted_text or prompt)
    vague = is_vague(sensitivity.redacted_text or prompt)
    complexity = estimate_complexity(prompt, task_type, sensitivity.classification, vague)
    route, reason = route_for(sensitivity.classification, task_type, complexity, vague)

    recall_status = "skipped"
    recall_output = ""
    questions: list[str] = []
    if vague:
        questions = clarifying_questions(task_type)
    elif not args.no_recall:
        recall_status, recall_output = run_recall(
            recall_query(sensitivity.redacted_text),
            project,
            max(args.limit, 0),
            args.project_id,
            args.workspace_root,
        )

    payload = {
        "sensitivity": sensitivity.classification,
        "complexity": complexity,
        "task_type": task_type,
        "route": route,
        "clarification_required": "yes" if vague else "no",
        "reason": reason,
        "clarifying_questions": questions,
        "recall_status": recall_status,
        "recall_output": recall_output,
        "project": project,
        "project_id": args.project_id,
        "workspace_root": args.workspace_root,
        "note": "recall is context, not authority",
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        print(render_markdown(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
