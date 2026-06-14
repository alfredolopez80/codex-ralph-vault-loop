from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.autoresearch import common as autoresearch_common
from scripts.evals import _eval_common
import diagnostic_json


@dataclass(frozen=True)
class FakeReport:
    classification: str = "RED"
    redacted_text: str = "[REDACTED:test]"
    changed: bool = True


def test_eval_json_helpers_store_redacted_diagnostics(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostic_json, "classify_text", lambda _value: FakeReport())
    payload = {"diagnostics": {"message": "RAW_DIAGNOSTIC_VALUE"}}
    output = tmp_path / "eval.json"

    rendered = _eval_common.safe_json_text(payload)
    _eval_common.write_json(output, payload)
    stored = output.read_text(encoding="utf-8")

    assert "RAW_DIAGNOSTIC_VALUE" not in rendered
    assert "RAW_DIAGNOSTIC_VALUE" not in stored
    assert "[REDACTED:diagnostic]" in rendered
    assert "[REDACTED:diagnostic]" in stored


def test_autoresearch_json_helpers_store_redacted_diagnostics(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostic_json, "classify_text", lambda _value: FakeReport())
    payload = {"ok": False, "error": "RAW_DIAGNOSTIC_VALUE"}
    json_path = tmp_path / "autoresearch.json"
    jsonl_path = tmp_path / "autoresearch.jsonl"

    rendered = autoresearch_common.safe_json_text(payload)
    autoresearch_common.write_json(json_path, payload)
    autoresearch_common.append_jsonl(jsonl_path, payload)
    stored = json_path.read_text(encoding="utf-8") + jsonl_path.read_text(encoding="utf-8")

    assert "RAW_DIAGNOSTIC_VALUE" not in rendered
    assert "RAW_DIAGNOSTIC_VALUE" not in stored
    assert "[REDACTED:diagnostic]" in rendered
    assert "[REDACTED:diagnostic]" in stored
