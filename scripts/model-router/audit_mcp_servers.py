#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client


REPO = Path("/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop")

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"[A-Za-z0-9]{20,}\.[A-Za-z0-9_\-]{8,}"),
]


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if not isinstance(value, str):
        return value
    text = value
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def content_text(result: Any) -> str:
    blocks = getattr(result, "content", []) or []
    parts = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@dataclass
class CheckResult:
    server: str
    tool: str
    ok: bool
    elapsed_ms: int
    detail: str = ""
    error: str = ""


@dataclass
class McpServer:
    name: str
    kind: str
    target: str
    args: list[str] = field(default_factory=list)
    env_names: list[str] = field(default_factory=list)
    cwd: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @asynccontextmanager
    async def session(self):
        if self.kind == "remote":
            async with streamablehttp_client(self.target, headers=self.headers, timeout=30) as (
                read,
                write,
                _session_id,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
            return

        env = os.environ.copy()
        missing = [name for name in self.env_names if not env.get(name)]
        if missing:
            raise RuntimeError(f"missing env vars: {', '.join(missing)}")
        params = StdioServerParameters(
            command=self.target,
            args=self.args,
            env=env,
            cwd=self.cwd,
        )
        async with stdio_client(params, errlog=open(os.devnull, "w")) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def servers() -> list[McpServer]:
    zai_key = required_env("Z_AI_API_KEY")
    return [
        McpServer(
            name="zai_web_search",
            kind="remote",
            target="https://api.z.ai/api/mcp/web_search_prime/mcp",
            headers={"Authorization": f"Bearer {zai_key}"},
        ),
        McpServer(
            name="zai_web_reader",
            kind="remote",
            target="https://api.z.ai/api/mcp/web_reader/mcp",
            headers={"Authorization": f"Bearer {zai_key}"},
        ),
        McpServer(
            name="zai_zread",
            kind="remote",
            target="https://api.z.ai/api/mcp/zread/mcp",
            headers={"Authorization": f"Bearer {zai_key}"},
        ),
        McpServer(
            name="zai_vision",
            kind="stdio",
            target="npx",
            args=["-y", "@z_ai/mcp-server@latest"],
            env_names=["Z_AI_API_KEY", "Z_AI_MODE"],
        ),
        McpServer(
            name="minimax_coding_tools",
            kind="stdio",
            target="/Users/alfredolopez/.local/bin/uvx",
            args=["minimax-coding-plan-mcp", "-y"],
            env_names=["MINIMAX_API_KEY", "MINIMAX_API_HOST"],
        ),
        McpServer(
            name="ralph_coding_models",
            kind="stdio",
            target=str(REPO / ".venv-model-router/bin/python"),
            args=[str(REPO / "scripts/model-router/ralph_coding_models_mcp.py")],
            env_names=[
                "Z_AI_API_KEY",
                "Z_AI_CODING_BASE_URL",
                "Z_AI_GENERAL_BASE_URL",
                "Z_AI_USE_CODING_ENDPOINT",
                "Z_AI_MODEL_DEEP",
                "Z_AI_MODEL_FAST",
                "MINIMAX_API_KEY",
                "MINIMAX_ANTHROPIC_BASE_URL",
                "MINIMAX_OPENAI_BASE_URL",
                "MINIMAX_MODEL_FAST",
                "MINIMAX_MODEL_STANDARD",
            ],
            cwd=str(REPO),
        ),
    ]


def schema_args(tool: str, schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    args: dict[str, Any] = {}
    for name, prop in properties.items():
        lname = name.lower()
        if lname in {"query", "q", "keyword", "keywords", "search_query"}:
            args[name] = "Codex CLI MCP configuration"
        elif lname in {"url", "uri", "link"}:
            args[name] = "https://example.com/"
        elif lname in {"repo", "repository", "repo_name"}:
            args[name] = "openai/codex"
        elif lname in {"owner"}:
            args[name] = "openai"
        elif lname in {"path", "file_path", "filepath"}:
            args[name] = "README.md"
        elif lname in {"prompt", "text", "content", "task"}:
            args[name] = "Return exactly one short sentence: MCP audit OK."
        elif lname == "system":
            args[name] = "Validation only. Be concise."
        elif lname == "task_type":
            args[name] = "openclaw_fast"
        elif lname == "complexity":
            args[name] = 2
        elif lname == "sensitivity":
            args[name] = "green"
        elif lname in {"max_tokens", "max_output_tokens"}:
            args[name] = 256
        elif lname == "temperature":
            args[name] = 0.1
        elif lname in {"image_url", "image", "input_image", "image_path", "image_source"}:
            args[name] = "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/Placeholder_view_vector.svg/320px-Placeholder_view_vector.svg.png"
        elif lname in {"expected_image_source", "actual_image_source"}:
            args[name] = "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/Placeholder_view_vector.svg/320px-Placeholder_view_vector.svg.png"
        elif lname in {"video_source", "video_url", "video"}:
            args[name] = "https://filesamples.com/samples/video/mp4/sample_640x360.mp4"
        elif lname in {"output_type"}:
            args[name] = "description"
        elif lname in {"return_format"}:
            args[name] = "text"
        elif lname in {"language"}:
            args[name] = "en"
        elif prop.get("default") is not None:
            continue
    if tool == "validate_coding_models":
        return {}
    if tool == "ensemble_counterpart":
        return {"prompt": "Return one short risk and one short recommendation for an MCP model router.", "sensitivity": "green"}
    return args


async def list_schemas() -> dict[str, Any]:
    output: dict[str, Any] = {}
    for server in servers():
        started = time.time()
        try:
            async with server.session() as session:
                tools = (await session.list_tools()).tools
            output[server.name] = {
                "ok": True,
                "elapsed_ms": int((time.time() - started) * 1000),
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.inputSchema,
                    }
                    for tool in tools
                ],
            }
        except Exception as exc:
            output[server.name] = {
                "ok": False,
                "elapsed_ms": int((time.time() - started) * 1000),
                "error": str(exc),
            }
    return output


async def call_tool(
    server: McpServer,
    tool_name: str,
    args: dict[str, Any],
    timeout: int = 90,
) -> CheckResult:
    started = time.time()
    try:
        async def _run() -> Any:
            async with server.session() as session:
                return await session.call_tool(tool_name, args)

        result = await asyncio.wait_for(_run(), timeout=timeout)
        text = content_text(result)
        detail = text[:500] if text else "returned content"
        return CheckResult(
            server=server.name,
            tool=tool_name,
            ok=not getattr(result, "isError", False),
            elapsed_ms=int((time.time() - started) * 1000),
            detail=detail,
        )
    except Exception as exc:
        return CheckResult(
            server=server.name,
            tool=tool_name,
            ok=False,
            elapsed_ms=int((time.time() - started) * 1000),
            error=str(exc),
        )


async def smoke_calls() -> list[dict[str, Any]]:
    schema_report = await list_schemas()
    by_name = {server.name: server for server in servers()}
    checks: list[CheckResult] = []
    for server_name, report in schema_report.items():
        if not report.get("ok"):
            checks.append(
                CheckResult(
                    server=server_name,
                    tool="__list_tools__",
                    ok=False,
                    elapsed_ms=report.get("elapsed_ms", 0),
                    error=report.get("error", ""),
                )
            )
            continue
        server = by_name[server_name]
        for tool in report.get("tools", []):
            args = schema_args(tool["name"], tool.get("inputSchema") or {})
            checks.append(await call_tool(server, tool["name"], args))
    return [scrub(check.__dict__) for check in checks]


async def single_call(server_name: str, tool_name: str, timeout: int) -> dict[str, Any]:
    by_name = {server.name: server for server in servers()}
    if server_name not in by_name:
        raise RuntimeError(f"unknown server: {server_name}")
    server = by_name[server_name]
    async with server.session() as session:
        tools = (await session.list_tools()).tools
    tool = next((item for item in tools if item.name == tool_name), None)
    if tool is None:
        raise RuntimeError(f"tool not found on {server_name}: {tool_name}")
    args = schema_args(tool.name, tool.inputSchema or {})
    result = await call_tool(server, tool.name, args, timeout=timeout)
    return scrub(result.__dict__)


async def suite(server_names: set[str] | None, timeout: int, skip_tools: set[str] | None = None) -> None:
    schema_report = await list_schemas()
    for server_name, report in schema_report.items():
        if server_names and server_name not in server_names:
            continue
        if not report.get("ok"):
            print(
                json.dumps(
                    scrub(
                        {
                            "server": server_name,
                            "tool": "__list_tools__",
                            "ok": False,
                            "elapsed_ms": report.get("elapsed_ms", 0),
                            "error": report.get("error", ""),
                        }
                    ),
                    ensure_ascii=False,
                ),
                flush=True,
            )
            continue
        for tool in report.get("tools", []):
            if skip_tools and tool["name"] in skip_tools:
                print(
                    json.dumps(
                        {
                            "server": server_name,
                            "tool": tool["name"],
                            "ok": None,
                            "elapsed_ms": 0,
                            "detail": "skipped by audit filter",
                            "error": "",
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                continue
            result = await single_call(server_name, tool["name"], timeout)
            print(json.dumps(result, ensure_ascii=False), flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schemas", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--server")
    parser.add_argument("--tool")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument(
        "--suite",
        choices=["official", "router", "all"],
        help="Run JSONL smoke tests with one line per tool.",
    )
    parser.add_argument("--skip-tool", action="append", default=[])
    args = parser.parse_args()
    if args.schemas:
        print(json.dumps(scrub(await list_schemas()), indent=2, ensure_ascii=False))
        return
    if args.smoke:
        print(json.dumps(await smoke_calls(), indent=2, ensure_ascii=False))
        return
    if args.server and args.tool:
        print(
            json.dumps(
                await single_call(args.server, args.tool, args.timeout),
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    if args.suite:
        official = {
            "zai_web_search",
            "zai_web_reader",
            "zai_zread",
            "zai_vision",
            "minimax_coding_tools",
        }
        router = {"ralph_coding_models"}
        selected = None
        if args.suite == "official":
            selected = official
        elif args.suite == "router":
            selected = router
        await suite(selected, args.timeout, set(args.skip_tool))
        return
    raise SystemExit("Use --schemas or --smoke")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": scrub(str(exc))}, ensure_ascii=False))
        sys.exit(1)
