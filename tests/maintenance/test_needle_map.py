from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "maintenance" / "needle_map.py"


def load_module():
    spec = importlib.util.spec_from_file_location("needle_map", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["needle_map"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_repo_map_skips_noisy_and_binary_paths(tmp_path: Path) -> None:
    module = load_module()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"fake")

    report = module.repo_map(tmp_path)

    assert report["file_count_sampled"] == 1
    assert report["sample_files"] == ["src/app.py"]
    assert ".py" in report["suffixes"]


def test_log_map_returns_compact_matching_lines(tmp_path: Path) -> None:
    module = load_module()
    log = tmp_path / "run.log"
    log.write_text("ignore\nfallback_used true\n" + ("x" * 8000), encoding="utf-8")

    report = module.log_map(tmp_path, "fallback_used", max_files=10, max_bytes=120, max_matches=5)

    assert report["result_count"] == 1
    assert report["results"][0]["path"] == "run.log"
    assert report["results"][0]["truncated"] is True
    assert report["results"][0]["matches"][0]["line"] == 2


def test_json_and_csv_modes_report_shape_without_full_dump(tmp_path: Path) -> None:
    module = load_module()
    json_path = tmp_path / "report.json"
    csv_path = tmp_path / "metrics.csv"
    json_path.write_text('{"selected_memory_ids":["node_a"],"large":"' + ("x" * 5000) + '"}', encoding="utf-8")
    csv_path.write_text("name,value\nlatency,12\nother,3\n", encoding="utf-8")

    json_report = module.json_map(json_path, "selected_memory_ids", max_bytes=2000)
    csv_report = module.csv_map(csv_path, "latency", max_bytes=2000, max_matches=5)

    assert json_report["shape"]["type"] in {"object", "jsonl"}
    assert json_report["truncated"] is True
    assert csv_report["columns"] == ["name", "value"]
    assert csv_report["matches"][0]["line"] == 2
