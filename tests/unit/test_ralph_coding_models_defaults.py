from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "model-router" / "ralph_coding_models_mcp.py"


def parsed_module() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))


def constants(tree: ast.Module) -> dict[str, int]:
    values: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                values[node.targets[0].id] = node.value.value
    return values


def functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_advisor_default_token_budgets_and_output_contract() -> None:
    tree = parsed_module()
    values = constants(tree)
    definitions = functions(tree)
    expected = {
        "zai_coding_deep": "ZAI_DEEP_DEFAULT_MAX_TOKENS",
        "zai_coding_fast": "ZAI_FAST_DEFAULT_MAX_TOKENS",
        "minimax_agentic_fast": "MINIMAX_FAST_DEFAULT_MAX_TOKENS",
        "minimax_agentic": "MINIMAX_STANDARD_DEFAULT_MAX_TOKENS",
    }
    assert {name: values[name] for name in expected.values()} == {
        "ZAI_DEEP_DEFAULT_MAX_TOKENS": 3000,
        "ZAI_FAST_DEFAULT_MAX_TOKENS": 1500,
        "MINIMAX_FAST_DEFAULT_MAX_TOKENS": 1500,
        "MINIMAX_STANDARD_DEFAULT_MAX_TOKENS": 2000,
    }
    source = MODULE_PATH.read_text(encoding="utf-8")
    for name, constant in expected.items():
        defaults = definitions[name].args.defaults
        assert any(isinstance(default, ast.Name) and default.id == constant for default in defaults)
        for field in ("verdict", "findings", "evidence", "risk", "next_action", "confidence"):
            assert field in source


def test_advisor_routes_keep_max_tokens_as_a_caller_parameter() -> None:
    names = {"zai_coding_deep", "zai_coding_fast", "minimax_agentic_fast", "minimax_agentic"}
    for name, function in functions(parsed_module()).items():
        if name in names:
            assert "max_tokens" in [argument.arg for argument in function.args.args]


@pytest.fixture()
def router_module(monkeypatch: pytest.MonkeyPatch):
    class FakeFastMCP:
        def __init__(self, _name: str) -> None:
            pass

        def tool(self):
            return lambda function: function

        def run(self) -> None:
            raise AssertionError("The fixture must not start an MCP server")

    mcp_package = types.ModuleType("mcp")
    mcp_server = types.ModuleType("mcp.server")
    mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")
    mcp_fastmcp.FastMCP = FakeFastMCP
    openai_module = types.ModuleType("openai")
    openai_module.OpenAI = object
    pydantic_module = types.ModuleType("pydantic")

    class FakeBaseModel:
        def __init__(self, **values: object) -> None:
            defaults = {"summary": "", "text": "", "risks": [], "error": None}
            self.__dict__.update(defaults)
            self.__dict__.update(values)

        def model_dump(self) -> dict[str, object]:
            return dict(self.__dict__)

    def fake_field(*, default_factory):
        return default_factory()

    pydantic_module.BaseModel = FakeBaseModel
    pydantic_module.Field = fake_field
    monkeypatch.setitem(sys.modules, "mcp", mcp_package)
    monkeypatch.setitem(sys.modules, "mcp.server", mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", mcp_fastmcp)
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setitem(sys.modules, "pydantic", pydantic_module)
    module_name = "ralph_coding_models_mcp_fixture"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("lane", "provider_function"),
    [
        ("zai_coding_deep", "call_zai"),
        ("zai_coding_fast", "call_zai"),
        ("minimax_agentic_fast", "call_minimax"),
        ("minimax_agentic", "call_minimax"),
    ],
)
def test_each_advisor_lane_returns_compact_contract_without_retry(router_module, monkeypatch, lane: str, provider_function: str) -> None:
    calls: list[dict[str, object]] = []
    structured_text = "\n".join(
        [
            "verdict: keep",
            "findings: fixture is healthy",
            "evidence: deterministic local provider stub",
            "risk: none",
            "next_action: continue local validation",
            "confidence: high",
        ]
    )

    def fake_provider(**kwargs):
        calls.append(kwargs)
        return router_module.ModelResult(
            provider="fixture",
            model="fixture-model",
            ok=True,
            elapsed_ms=1,
            summary=structured_text,
            text=structured_text,
        )

    monkeypatch.setattr(router_module, provider_function, fake_provider)
    result = getattr(router_module, lane)(prompt="GREEN deterministic lane fixture", sensitivity="green")

    assert len(calls) == 1
    assert result["ok"] is True
    assert "truncated" not in result["text"].lower()
    for field in ("verdict", "findings", "evidence", "risk", "next_action", "confidence"):
        assert f"{field}:" in result["text"]
