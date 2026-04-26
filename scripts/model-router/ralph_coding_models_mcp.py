#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import time
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from pydantic import BaseModel, Field

try:
    import anthropic
except Exception:
    anthropic = None


mcp = FastMCP("ralph_coding_models")

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"),
    re.compile(r"\bghp_[0-9A-Za-z]{20,}\b"),
    re.compile(r"\bgithub_pat_[0-9A-Za-z_]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|private[_-]?key)\s*[:=]\s*[^\s]+"
    ),
]


class ModelResult(BaseModel):
    provider: str
    model: str
    ok: bool
    elapsed_ms: int
    summary: str = ""
    text: str = ""
    risks: list[str] = Field(default_factory=list)
    error: str | None = None


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def guard(prompt: str, sensitivity: str) -> None:
    if sensitivity.lower() == "red":
        raise ValueError("Refusing external call: sensitivity=RED")
    if contains_secret(prompt):
        raise ValueError("Refusing external call: possible secret detected")


def zai_base_url() -> str:
    use_coding = os.environ.get("Z_AI_USE_CODING_ENDPOINT", "false").lower() == "true"
    if use_coding:
        return os.environ.get("Z_AI_CODING_BASE_URL", "https://api.z.ai/api/coding/paas/v4")
    return os.environ.get("Z_AI_GENERAL_BASE_URL", "https://api.z.ai/api/paas/v4")


def zai_client() -> OpenAI:
    key = os.environ.get("Z_AI_API_KEY")
    if not key:
        raise RuntimeError("Z_AI_API_KEY is not set")
    return OpenAI(api_key=key, base_url=zai_base_url())


def call_zai(
    *,
    model: str,
    prompt: str,
    system: str,
    max_tokens: int,
    temperature: float = 0.2,
) -> ModelResult:
    started = time.time()
    try:
        response = zai_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = response.choices[0].message.content or ""
        return ModelResult(
            provider="zai",
            model=model,
            ok=True,
            elapsed_ms=int((time.time() - started) * 1000),
            summary=text[:1200],
            text=text,
        )
    except Exception as exc:
        return ModelResult(
            provider="zai",
            model=model,
            ok=False,
            elapsed_ms=int((time.time() - started) * 1000),
            error=str(exc),
        )


def call_minimax_anthropic(
    *,
    model: str,
    prompt: str,
    system: str,
    max_tokens: int,
) -> ModelResult:
    started = time.time()
    if anthropic is None:
        raise RuntimeError("anthropic package is not installed")
    key = os.environ.get("MINIMAX_API_KEY")
    if not key:
        raise RuntimeError("MINIMAX_API_KEY is not set")
    base_url = os.environ.get("MINIMAX_ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
    try:
        client = anthropic.Anthropic(api_key=key, base_url=base_url)
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts = [
            block.text for block in message.content if getattr(block, "type", None) == "text"
        ]
        text = "\n".join(text_parts)
        return ModelResult(
            provider="minimax",
            model=model,
            ok=True,
            elapsed_ms=int((time.time() - started) * 1000),
            summary=text[:1200],
            text=text,
        )
    except Exception as exc:
        return ModelResult(
            provider="minimax",
            model=model,
            ok=False,
            elapsed_ms=int((time.time() - started) * 1000),
            error=str(exc),
        )


def call_minimax_openai(
    *,
    model: str,
    prompt: str,
    system: str,
    max_tokens: int,
) -> ModelResult:
    started = time.time()
    key = os.environ.get("MINIMAX_API_KEY")
    if not key:
        raise RuntimeError("MINIMAX_API_KEY is not set")
    base_url = os.environ.get("MINIMAX_OPENAI_BASE_URL", "https://api.minimax.io/v1")
    try:
        client = OpenAI(api_key=key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        text = response.choices[0].message.content or ""
        return ModelResult(
            provider="minimax",
            model=model,
            ok=True,
            elapsed_ms=int((time.time() - started) * 1000),
            summary=text[:1200],
            text=text,
        )
    except Exception as exc:
        return ModelResult(
            provider="minimax",
            model=model,
            ok=False,
            elapsed_ms=int((time.time() - started) * 1000),
            error=str(exc),
        )


def call_minimax(
    *,
    model: str,
    prompt: str,
    system: str,
    max_tokens: int,
) -> ModelResult:
    result = call_minimax_anthropic(
        model=model,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
    )
    if result.ok:
        return result
    fallback = call_minimax_openai(
        model=model,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
    )
    if fallback.ok:
        return fallback
    fallback.risks.append(f"Anthropic-compatible endpoint also failed: {result.error}")
    return fallback


@mcp.tool()
def validate_coding_models() -> dict[str, Any]:
    deep = os.environ.get("Z_AI_MODEL_DEEP", "glm-5.1")
    fast = os.environ.get("Z_AI_MODEL_FAST", "glm-5-turbo")
    mm_fast = os.environ.get("MINIMAX_MODEL_FAST", "MiniMax-M2.7-highspeed")
    results = {
        "zai_deep": call_zai(
            model=deep,
            system="Validation only. Reply compactly.",
            prompt='Reply exactly: {"model":"glm-5.1","status":"ok"}',
            max_tokens=128,
        ).model_dump(),
        "zai_fast": call_zai(
            model=fast,
            system="Validation only. Reply compactly.",
            prompt='Reply exactly: {"model":"glm-5-turbo","status":"ok"}',
            max_tokens=128,
        ).model_dump(),
        "minimax_fast": call_minimax(
            model=mm_fast,
            system="Validation only. Reply compactly.",
            prompt='Reply exactly: {"model":"MiniMax-M2.7-highspeed","status":"ok"}',
            max_tokens=128,
        ).model_dump(),
    }
    results["summary"] = {
        "zai_deep_ok": results["zai_deep"]["ok"],
        "zai_fast_ok": results["zai_fast"]["ok"],
        "minimax_fast_ok": results["minimax_fast"]["ok"],
        "all_ok": (
            results["zai_deep"]["ok"]
            and results["zai_fast"]["ok"]
            and results["minimax_fast"]["ok"]
        ),
    }
    return results


@mcp.tool()
def zai_coding_deep(
    prompt: str,
    system: str = "You are GLM-5.1 acting as a strong engineering counterpart to Codex. Analyze deeply, identify risks, and propose concrete next steps.",
    max_tokens: int = 6000,
    sensitivity: Literal["green", "yellow", "red"] = "yellow",
) -> dict[str, Any]:
    guard(prompt, sensitivity)
    model = os.environ.get("Z_AI_MODEL_DEEP", "glm-5.1")
    return call_zai(
        model=model,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=0.2,
    ).model_dump()


@mcp.tool()
def zai_coding_fast(
    prompt: str,
    system: str = "You are GLM-5-Turbo optimized for fast OpenClaw-like coding tasks. Follow commands, keep state, and return concise actionable output.",
    max_tokens: int = 3000,
    sensitivity: Literal["green", "yellow", "red"] = "yellow",
) -> dict[str, Any]:
    guard(prompt, sensitivity)
    model = os.environ.get("Z_AI_MODEL_FAST", "glm-5-turbo")
    return call_zai(
        model=model,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=0.2,
    ).model_dump()


@mcp.tool()
def minimax_agentic_fast(
    prompt: str,
    system: str = "You are MiniMax-M2.7-highspeed. Handle fast agentic coding support, logs, diffs, test ideas, and concise implementation advice.",
    max_tokens: int = 4000,
    sensitivity: Literal["green", "yellow", "red"] = "yellow",
) -> dict[str, Any]:
    guard(prompt, sensitivity)
    model = os.environ.get("MINIMAX_MODEL_FAST", "MiniMax-M2.7-highspeed")
    return call_minimax(
        model=model,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
    ).model_dump()


@mcp.tool()
def minimax_agentic(
    prompt: str,
    system: str = "You are MiniMax-M2.7. Provide concise agentic coding support.",
    max_tokens: int = 4000,
    sensitivity: Literal["green", "yellow", "red"] = "yellow",
) -> dict[str, Any]:
    guard(prompt, sensitivity)
    model = os.environ.get("MINIMAX_MODEL_STANDARD", "MiniMax-M2.7")
    return call_minimax(
        model=model,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
    ).model_dump()


@mcp.tool()
def route_coding_task(
    task_type: Literal[
        "openclaw_fast",
        "agentic_fast",
        "log_summary",
        "diff_summary",
        "test_ideas",
        "medium_analysis",
        "architecture_counterpart",
        "code_review",
        "problem_diagnosis",
    ],
    prompt: str,
    complexity: int = 3,
    sensitivity: Literal["green", "yellow", "red"] = "yellow",
) -> dict[str, Any]:
    guard(prompt, sensitivity)
    if complexity <= 2:
        if task_type in {"log_summary", "diff_summary", "test_ideas", "agentic_fast"}:
            return {
                "route": "minimax_agentic_fast",
                "reason": "Low-complexity fast task; MiniMax highspeed is preferred.",
                "result": minimax_agentic_fast(prompt=prompt, sensitivity=sensitivity),
            }
        return {
            "route": "zai_coding_fast",
            "reason": "Low-complexity OpenClaw-like task; GLM-5-Turbo is preferred.",
            "result": zai_coding_fast(prompt=prompt, sensitivity=sensitivity),
        }
    if complexity <= 4:
        if task_type in {"openclaw_fast", "agentic_fast"}:
            return {
                "route": "zai_coding_fast",
                "reason": "Agentic command-following task; GLM-5-Turbo is preferred.",
                "result": zai_coding_fast(prompt=prompt, sensitivity=sensitivity),
            }
        return {
            "route": "minimax_agentic_fast",
            "reason": "Fast bounded coding support; MiniMax highspeed is preferred.",
            "result": minimax_agentic_fast(prompt=prompt, sensitivity=sensitivity),
        }
    return {
        "route": "zai_coding_deep",
        "reason": "Medium/high complexity; GLM-5.1 is used as Codex counterpart.",
        "result": zai_coding_deep(prompt=prompt, sensitivity=sensitivity),
    }


@mcp.tool()
def ensemble_counterpart(
    prompt: str,
    sensitivity: Literal["green", "yellow", "red"] = "yellow",
) -> dict[str, Any]:
    guard(prompt, sensitivity)
    return {
        "zai_glm51": zai_coding_deep(prompt=prompt, sensitivity=sensitivity),
        "minimax_highspeed": minimax_agentic_fast(prompt=prompt, sensitivity=sensitivity),
        "policy": "External models advise; Codex main decides.",
    }


if __name__ == "__main__":
    mcp.run()
