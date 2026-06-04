# PHASE 13 Checkpoint - MCP Eval Coverage

`docs/migration/checkpoints/PHASE_12.md` was reviewed first. It is marked PASS, so Phase 13 was allowed to proceed.

This phase adds three MCP-focused eval scripts. `scripts/evals/research_eval.py` scores citation quality for Z.ai and MiniMax research routes. `scripts/evals/vision_eval.py` scores analysis-only vision output for OCR, diagram reading, UI diffs, and generation avoidance. `scripts/evals/coding_model_eval.py` scores `ralph_coding_models` routing outcomes against the deterministic cost-router policy.

The fixtures live under `tests/evals/fixtures/research_citation`, `tests/evals/fixtures/vision_analysis`, and `tests/evals/fixtures/coding_model_tasks`. Each script supports `--mode mock` and `--mode live`. Mock mode uses committed fixtures. Live mode accepts `--live-response` with sanitized MCP output. If no live response is provided, the script writes a `skipped_no_mcp_bridge` report and exits 0 instead of faking an MCP call.

Reports are written to `.ralph-codex/reports/evals`. Each run also appends a JSONL summary through the shared helper in `scripts/evals/_mcp_eval_common.py`.

Research metrics cover source quality, faithfulness, recency fit, source diversity, actionability, plus cost. Vision metrics cover OCR correctness, diagram understanding, UI diff correctness, no generation usage, plus safety. Coding model metrics cover route correctness, acceptance rate, rework rate, latency score, plus sensitive externalization incidents.

Rules enforced: no image, video, or audio generation; GPT Images 2 remains outside these evals; RED content stays blocked. The coding fixture includes a RED task and records zero sensitive externalization incidents.

Manual validation:

All commands below were run with `PYTHONDONTWRITEBYTECODE=1`.

```text
python3 scripts/evals/research_eval.py --mode mock
python3 scripts/evals/coding_model_eval.py --mode mock
python3 scripts/evals/vision_eval.py --mode mock
python3 -m pytest tests/evals -q
```

Results: research score `1.0`, vision score `1.0`, coding router score `0.95`, and pytest reported `16 passed`.

Live behavior was checked with all three scripts in `--mode live` without a response file. Each generated a `skipped_no_mcp_bridge` report. A pytest case also verifies that `--mode live --live-response <json>` scores a sanitized response.

Security checks were run against the new files. No literal API keys were found. No direct Z.ai or MiniMax `model_provider` configuration was added.

Decision: PASS
