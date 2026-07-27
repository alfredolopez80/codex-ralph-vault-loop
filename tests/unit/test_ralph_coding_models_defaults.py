from __future__ import annotations

import ast
from pathlib import Path


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
