#!/usr/bin/env python3
"""Codex Stop hook that asks Codex to rewrite slop-heavy prose responses."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_THRESHOLD = 60
MIN_WORDS = 10
MAX_TEXT_BYTES = 60_000
SCHEMA_VERSION = 2
EVENT_NAME = "codex_stop_slop_guard"
ALLOWED_ACTIONS = {"block", "allow", "skip", "advisory"}
DEFAULT_PROSE_ACTION = "block"
DEFAULT_OPERATIONAL_ACTION = "skip"
DEFAULT_STRUCTURED_ACTION = "skip"
ANALYZER_COMMAND = ("uvx", "--from", "slop-guard", "sg", "-j", "-")
ANALYZER_ENV_ALLOWLIST = {
    "HOME",
    "PATH",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "UV_CACHE_DIR",
    "XDG_CACHE_HOME",
}
SENSITIVE_ENV_RE = re.compile(r"(?i)(secret|token|credential|api_?key|password|wallet|cookie)")

COMMAND_RE = re.compile(
    r"^\s*(?:\$\s*)?(?:"
    r"PYTEST_[A-Z0-9_]+=|[A-Z][A-Z0-9_]+=|python3?|bash|git|npm|pnpm|sfw|uvx|make|curl|"
    r"docker|kubectl|cp|mkdir|printf|sed|rg|ls|cat|tail|head|chmod|node|npx"
    r")\b"
)
LOG_LINE_RE = re.compile(r"^\s*(?:\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}|\[[A-Z]+\]|(?:INFO|WARN|ERROR|DEBUG)\b)")
YAML_KEY_RE = re.compile(r"^\s*[A-Za-z0-9_.-]+:\s*.*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
TASK_PACKET_LABELS = ("objective", "constraints", "commands", "validation", "done when", "criterios", "validacion")
OPERATIONAL_PHRASES = (
    "/goal",
    "goal prompt",
    "copy this prompt",
    "paste this prompt",
    "paste this into codex",
    "pega este prompt",
    "copiar este prompt",
    "prompt para ejecutar",
    "prompt operativo",
    "task packet",
)


@dataclass(frozen=True)
class PolicyConfig:
    enabled: bool
    threshold: int
    prose_action: str
    operational_action: str
    structured_action: str
    log_detail: str


@dataclass(frozen=True)
class TextFeatures:
    word_count: int
    byte_length: int
    line_count: int
    nonempty_line_count: int
    bullet_line_count: int
    bullet_ratio: float
    numbered_line_count: int
    code_fence_count: int
    table_like_line_count: int
    command_like_line_count: int
    log_like_line_count: int
    path_like_line_count: int
    json_like: bool
    yaml_like: bool
    message_sha256: str


@dataclass(frozen=True)
class ResponseClassification:
    category: str
    mode: str
    reason: str
    features: TextFeatures


@dataclass(frozen=True)
class AnalyzerInvocation:
    result: dict[str, Any] | None
    exit_code: int | None
    error_kind: str | None


@dataclass(frozen=True)
class PolicyDecision:
    mode: str
    policy_action: str
    should_run_analyzer: bool
    should_block: bool
    reason: str | None


def respond(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True))


def word_count(text: str) -> int:
    return len(text.split())


def threshold(env: Mapping[str, str] | None = None) -> int:
    return parse_threshold((env or os.environ).get("CODEX_SLOP_GUARD_THRESHOLD", str(DEFAULT_THRESHOLD)))


def parse_threshold(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    return max(0, min(100, value))


def parse_action(raw: str | None, default: str) -> str:
    value = (raw or default).strip().lower()
    return value if value in ALLOWED_ACTIONS else default


def parse_policy_config(env: Mapping[str, str] | None = None) -> PolicyConfig:
    source = env or os.environ
    return PolicyConfig(
        enabled=source.get("CODEX_SLOP_GUARD_ENABLED", "1") != "0",
        threshold=threshold(source),
        prose_action=parse_action(source.get("CODEX_SLOP_GUARD_PROSE_MODE"), DEFAULT_PROSE_ACTION),
        operational_action=parse_action(source.get("CODEX_SLOP_GUARD_OPERATIONAL_MODE"), DEFAULT_OPERATIONAL_ACTION),
        structured_action=parse_action(source.get("CODEX_SLOP_GUARD_STRUCTURED_MODE"), DEFAULT_STRUCTURED_ACTION),
        log_detail="debug" if source.get("CODEX_SLOP_GUARD_LOG_DETAIL", "normal").strip().lower() == "debug" else "normal",
    )


def line_ratio(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def looks_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return True


def extract_text_features(text: str) -> TextFeatures:
    lines = text.splitlines()
    nonempty = [line for line in lines if line.strip()]
    nonempty_count = len(nonempty)
    bullet_count = sum(1 for line in nonempty if re.match(r"^\s*[-*+]\s+\S", line))
    numbered_count = sum(1 for line in nonempty if re.match(r"^\s*\d+[.)]\s+\S", line))
    code_fence_count = sum(1 for line in lines if line.strip().startswith("```"))
    table_count = sum(1 for line in nonempty if line.count("|") >= 2 or TABLE_SEPARATOR_RE.match(line))
    command_count = sum(1 for line in nonempty if COMMAND_RE.match(line))
    log_count = sum(1 for line in nonempty if LOG_LINE_RE.match(line))
    path_count = sum(
        1
        for line in nonempty
        if "/Users/" in line
        or line.strip().startswith(("./", "../", "/"))
        or re.search(r"\.(?:py|json|md|toml|yaml|yml|sh|txt|html)\b", line)
    )
    yaml_key_count = sum(1 for line in nonempty if YAML_KEY_RE.match(line))
    json_like = looks_json(text)
    yaml_like = bool(nonempty_count >= 3 and yaml_key_count / nonempty_count >= 0.55 and not json_like)
    encoded = text.encode("utf-8")
    return TextFeatures(
        word_count=word_count(text),
        byte_length=len(encoded),
        line_count=len(lines),
        nonempty_line_count=nonempty_count,
        bullet_line_count=bullet_count,
        bullet_ratio=line_ratio(bullet_count, nonempty_count),
        numbered_line_count=numbered_count,
        code_fence_count=code_fence_count,
        table_like_line_count=table_count,
        command_like_line_count=command_count,
        log_like_line_count=log_count,
        path_like_line_count=path_count,
        json_like=json_like,
        yaml_like=yaml_like,
        message_sha256=hashlib.sha256(encoded).hexdigest(),
    )


def default_mode(category: str) -> str:
    if category == "prose":
        return "prose_blocking"
    if category == "unavailable":
        return "unavailable_allow"
    return f"{category}_skip"


def task_packet_score(lower_text: str) -> int:
    return sum(1 for label in TASK_PACKET_LABELS if f"{label}:" in lower_text)


def classify_response(text: str, features: TextFeatures | None = None) -> ResponseClassification:
    features = features or extract_text_features(text)
    if features.byte_length > MAX_TEXT_BYTES:
        return ResponseClassification("oversize", "oversize_skip", "above_max_bytes", features)

    lower = text.lower()
    operational_explicit = any(phrase in lower for phrase in OPERATIONAL_PHRASES)
    operational_packet = task_packet_score(lower) >= 3 and (
        features.bullet_line_count + features.numbered_line_count + features.command_like_line_count >= 3
    )
    if operational_explicit or operational_packet:
        return ResponseClassification("operational", "operational_skip", "operational_output", features)

    nonempty = features.nonempty_line_count
    table_dominant = features.table_like_line_count >= 2 and line_ratio(features.table_like_line_count, nonempty) >= 0.3
    command_dominant = features.command_like_line_count >= 3 and line_ratio(features.command_like_line_count, nonempty) >= 0.35
    log_dominant = features.log_like_line_count >= 3 and line_ratio(features.log_like_line_count, nonempty) >= 0.4
    code_dominant = features.code_fence_count >= 2 and nonempty <= 20
    path_dominant = features.path_like_line_count >= 4 and line_ratio(features.path_like_line_count, nonempty) >= 0.45
    if features.json_like or features.yaml_like or table_dominant or command_dominant or log_dominant or code_dominant or path_dominant:
        return ResponseClassification("structured", "structured_skip", "structured_output", features)

    if features.word_count < MIN_WORDS:
        return ResponseClassification("short", "short_skip", "below_min_words", features)

    return ResponseClassification("prose", "prose_blocking", "prose_output", features)


def effective_mode(category: str, action: str) -> str:
    if category == "prose" and action == "block":
        return "prose_blocking"
    if category == "unavailable" and action == "allow":
        return "unavailable_allow"
    return f"{category}_{action}"


def action_for_classification(config: PolicyConfig, classification: ResponseClassification) -> str:
    if classification.category in {"short", "oversize"}:
        return "skip"
    if classification.category == "operational":
        return config.operational_action
    if classification.category == "structured":
        return config.structured_action
    return config.prose_action


def pre_analyzer_decision(config: PolicyConfig, classification: ResponseClassification) -> PolicyDecision:
    action = action_for_classification(config, classification)
    mode = classification.mode if action == "skip" else effective_mode(classification.category, action)
    return PolicyDecision(
        mode=mode,
        policy_action=action,
        should_run_analyzer=action in {"block", "allow", "advisory"},
        should_block=False,
        reason=classification.reason if action == "skip" else None,
    )


def post_analyzer_decision(
    config: PolicyConfig, classification: ResponseClassification, result: dict[str, Any]
) -> PolicyDecision:
    action = action_for_classification(config, classification)
    score = parse_score(result.get("score"), 100)
    if score is None:
        score = 100
    blocked = action == "block" and score < config.threshold
    return PolicyDecision(
        mode=effective_mode(classification.category, action),
        policy_action=action,
        should_run_analyzer=True,
        should_block=blocked,
        reason="below_threshold" if blocked else None,
    )


def build_analyzer_command() -> list[str]:
    return list(ANALYZER_COMMAND)


def invoke_analyzer(text: str, command: Sequence[str] | None = None) -> AnalyzerInvocation:
    try:
        completed = subprocess.run(
            list(command or build_analyzer_command()),
            input=text,
            text=True,
            capture_output=True,
            env=analyzer_environment(),
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return AnalyzerInvocation(None, None, "not_found")
    except subprocess.TimeoutExpired:
        return AnalyzerInvocation(None, None, "timeout")
    except Exception:
        return AnalyzerInvocation(None, None, "exception")
    if completed.returncode not in (0, 1):
        return AnalyzerInvocation(None, completed.returncode, "exit_nonstandard")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return AnalyzerInvocation(None, completed.returncode, "invalid_json")
    if not isinstance(result, dict):
        return AnalyzerInvocation(None, completed.returncode, "invalid_result")
    if "score" in result and parse_score(result.get("score")) is None:
        return AnalyzerInvocation(None, completed.returncode, "invalid_score")
    return AnalyzerInvocation(result, completed.returncode, None)


def analyzer_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = env or os.environ
    return {
        key: value
        for key, value in source.items()
        if key in ANALYZER_ENV_ALLOWLIST and not SENSITIVE_ENV_RE.search(key)
    }


def parse_score(value: object, default: int | None = None) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def run_slop_guard(text: str) -> dict[str, Any]:
    invocation = invoke_analyzer(text)
    if invocation.error_kind or invocation.result is None:
        raise RuntimeError(invocation.error_kind or "slop_guard_failed")
    return invocation.result


def hook_source(script_path: Path | None = None, home: Path | None = None) -> str:
    path = (script_path or Path(__file__)).resolve()
    global_hooks = (home or Path.home()) / ".codex" / "hooks"
    try:
        path.relative_to(global_hooks.resolve())
        return "global"
    except ValueError:
        pass
    if path.name == "codex_stop_slop_guard.py" and path.parent.name == "gates" and path.parent.parent.name == "scripts":
        return "repo"
    return "unknown"


def safe_cwd(hook_input: Mapping[str, Any]) -> str:
    raw = hook_input.get("cwd")
    if isinstance(raw, str) and raw.strip():
        return raw
    return os.getcwd()


def infer_repo(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    repo = result.stdout.strip()
    return repo or None


def build_log_record(
    *,
    hook_input: Mapping[str, Any],
    config: PolicyConfig,
    classification: ResponseClassification | None,
    decision: PolicyDecision | None,
    score: int | None,
    band: str | None,
    blocked: bool,
    reason: str | None,
    analyzer_invocation: AnalyzerInvocation | None = None,
) -> dict[str, Any]:
    cwd = safe_cwd(hook_input)
    features = classification.features if classification else None
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "event": EVENT_NAME,
        "hook_source": hook_source(),
        "cwd": cwd,
        "repo": infer_repo(cwd),
        "threshold": config.threshold,
        "enabled": config.enabled,
        "mode": decision.mode if decision else (classification.mode if classification else "unavailable_allow"),
        "policy_action": decision.policy_action if decision else "allow",
        "score": score,
        "band": band,
        "blocked": blocked,
        "reason": reason,
        "word_count": features.word_count if features else 0,
        "line_count": features.line_count if features else 0,
        "bullet_line_count": features.bullet_line_count if features else 0,
        "bullet_ratio": features.bullet_ratio if features else 0.0,
        "numbered_line_count": features.numbered_line_count if features else 0,
        "code_fence_count": features.code_fence_count if features else 0,
        "table_like_line_count": features.table_like_line_count if features else 0,
        "command_like_line_count": features.command_like_line_count if features else 0,
        "json_like": features.json_like if features else False,
        "yaml_like": features.yaml_like if features else False,
        "message_sha256": features.message_sha256 if features else None,
        "analyzer_command": list(ANALYZER_COMMAND),
        "analyzer_exit_code": analyzer_invocation.exit_code if analyzer_invocation else None,
        "analyzer_error_kind": analyzer_invocation.error_kind if analyzer_invocation else None,
    }


def log_path() -> Path:
    return Path.home() / ".ralph-codex" / "logs" / "slop_guard_hooks.jsonl"


def write_log_record(record: Mapping[str, Any]) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(record), ensure_ascii=True, sort_keys=True) + "\n")
    except OSError:
        pass


def log_result(score: int | None, band: str | None, blocked: bool, reason: str | None = None) -> None:
    config = parse_policy_config()
    write_log_record(
        build_log_record(
            hook_input={},
            config=config,
            classification=None,
            decision=PolicyDecision("unavailable_allow", "allow", False, blocked, reason),
            score=score,
            band=band,
            blocked=blocked,
            reason=reason,
        )
    )


def block_reason(score: int, band: str, floor: int, result: Mapping[str, Any]) -> str:
    return (
        f"slop-guard scored the drafted response {score}/100 ({band}), below the "
        f"required threshold {floor}. Rewrite the final answer before sending it. "
        "Keep concrete facts, remove filler, avoid stock AI phrasing, reduce list-heavy "
        "structure when prose is clearer, and preserve all technical claims."
    )


def main() -> int:
    config = parse_policy_config()
    if not config.enabled:
        return 0

    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        decision = PolicyDecision("unavailable_allow", "allow", False, False, "invalid_hook_input")
        write_log_record(
            build_log_record(
                hook_input={},
                config=config,
                classification=None,
                decision=decision,
                score=None,
                band=None,
                blocked=False,
                reason="invalid_hook_input",
            )
        )
        return 0
    if not isinstance(hook_input, dict):
        return 0

    if hook_input.get("stop_hook_active"):
        return 0

    text = hook_input.get("last_assistant_message") or ""
    if not isinstance(text, str):
        text = ""

    classification = classify_response(text)
    pre_decision = pre_analyzer_decision(config, classification)
    if not pre_decision.should_run_analyzer:
        write_log_record(
            build_log_record(
                hook_input=hook_input,
                config=config,
                classification=classification,
                decision=pre_decision,
                score=None,
                band=None,
                blocked=False,
                reason=pre_decision.reason,
            )
        )
        return 0

    invocation = invoke_analyzer(text)
    if invocation.error_kind or invocation.result is None:
        unavailable = PolicyDecision("unavailable_allow", "allow", False, False, "analyzer_unavailable")
        write_log_record(
            build_log_record(
                hook_input=hook_input,
                config=config,
                classification=classification,
                decision=unavailable,
                score=None,
                band=None,
                blocked=False,
                reason="analyzer_unavailable",
                analyzer_invocation=invocation,
            )
        )
        return 0

    result = invocation.result
    score = parse_score(result.get("score"), 100)
    if score is None:
        unavailable = PolicyDecision("unavailable_allow", "allow", False, False, "analyzer_unavailable")
        invalid_score = AnalyzerInvocation(None, invocation.exit_code, "invalid_score")
        write_log_record(
            build_log_record(
                hook_input=hook_input,
                config=config,
                classification=classification,
                decision=unavailable,
                score=None,
                band=None,
                blocked=False,
                reason="analyzer_unavailable",
                analyzer_invocation=invalid_score,
            )
        )
        return 0
    band = str(result.get("band", "unknown"))
    post_decision = post_analyzer_decision(config, classification, result)
    write_log_record(
        build_log_record(
            hook_input=hook_input,
            config=config,
            classification=classification,
            decision=post_decision,
            score=score,
            band=band,
            blocked=post_decision.should_block,
            reason=post_decision.reason,
            analyzer_invocation=invocation,
        )
    )

    if post_decision.should_block:
        respond({"decision": "block", "reason": block_reason(score, band, config.threshold, result)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
