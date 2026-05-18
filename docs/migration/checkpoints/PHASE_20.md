# PHASE 20 Checkpoint - Full Acceptance Run

`docs/migration/checkpoints/PHASE_19.md` was reviewed first. It is marked PASS, so FASE 20 was allowed to proceed.

## Acceptance Summary

| Subsystem                       | Result | Evidence                                                                                                                                                     |
| ------------------------------- | -----: | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Codex App repo readiness        |   PASS | Current Codex App session loaded this repo and project `AGENTS.md`; `scripts/setup/doctor.sh` passed.                                                        |
| `AGENTS.md` load surface        |   PASS | `AGENTS.md` exists and is validated by repo doctor.                                                                                                          |
| Skills detectable               |   PASS | 16 skills under `.agents/skills/*/SKILL.md` have `name` and `description` frontmatter.                                                                       |
| Codex config TOML               |   PASS | `.codex/config.toml` parses with Python `tomllib`.                                                                                                           |
| Subagents TOML                  |   PASS | 12 `.codex/agents/*.toml` files parse and include `name`, `description`, and `developer_instructions`.                                                       |
| Hooks dry-run                   |   PASS | Every `.codex/hooks/*.py` executed with `{}` and temporary `RALPH_HOME`.                                                                                     |
| Vault temporary integration     |   PASS | `vault-init`, GREEN/YELLOW save, RED skip, and search passed with temporary `VAULT_DIR`.                                                                     |
| Vault real read-only check      |   PASS | `~/Documents/Obsidian/MiVault` exists and `vault-search.py` ran read-only with a no-match probe.                                                             |
| Memory integration              |   PASS | `wakeup.py`, `handoff.py`, and RED classification passed with temporary `RALPH_HOME`.                                                                        |
| Gates                           |   PASS | `scripts/gates/run-gates.py --minimal` produced reports and 0 failures.                                                                                      |
| Unit tests                      |   PASS | 17 passed.                                                                                                                                                   |
| Integration tests               |   PASS | 18 passed.                                                                                                                                                   |
| Eval tests                      |   PASS | 17 passed.                                                                                                                                                   |
| Full test suite                 |   PASS | 52 passed.                                                                                                                                                   |
| Scorecards                      |   PASS | `cost_router_v1` scored 1.0 with all hard gates passing.                                                                                                     |
| Research eval                   |   PASS | Mock eval scored 1.0.                                                                                                                                        |
| Vision eval                     |   PASS | Mock eval scored 1.0 and `generation_allowed=false`.                                                                                                         |
| Coding model eval               |   PASS | Mock eval scored 0.95 with `sensitive_externalization_incidents=0`.                                                                                          |
| AutoResearch                    |   PASS | Toy dry-run decision `keep`, holdout delta `0.2143`, hard gates passed, no harness/fixture mutation.                                                         |
| E2E orchestrator dry-run        |   PASS | Temporary Obsidian spec generated an implementation plan and cost-route decision without repo code edits.                                                    |
| RED policy                      |   PASS | RED content blocks external routing, redaction reports `allowed_external=false`, and vault save skips persistence.                                           |
| Visual generation policy        |   PASS | `GPT Imágenes 2` remains the only approved visual generation route; Z.ai/MiniMax generation is prohibited.                                                   |
| Codex final ownership           |   PASS | `Codex main decides` / `Codex main owns` is present in root and routing docs.                                                                                |
| No direct Z.ai/MiniMax provider |   PASS | Grep found only historical checkpoint text documenting absence of direct providers.                                                                          |
| MCP availability                |   PASS | `mcp__ralph_coding_models__.validate_coding_models` returned `all_ok=true`; Z.ai and MiniMax tool namespaces are exposed in the current Codex tool registry. |
| Coding models                   |   PASS | `glm-5.1`, `glm-5-turbo`, and `MiniMax-M2.7-highspeed` validated successfully through `ralph_coding_models`.                                                 |

## Commands Executed

```text
sed -n '1,260p' docs/migration/checkpoints/PHASE_19.md
bash scripts/setup/doctor.sh
python3 - <<'PY'
from pathlib import Path
import tomllib
tomllib.loads(Path('.codex/config.toml').read_text(encoding='utf-8'))
for path in sorted(Path('.codex/agents').glob('*.toml')):
    data = tomllib.loads(path.read_text(encoding='utf-8'))
    assert data.get('name')
    assert data.get('description')
    assert data.get('developer_instructions')
print('PHASE_20_TOML_OK')
PY
python3 - <<'PY'
from pathlib import Path
skills = sorted(Path('.agents/skills').glob('*/SKILL.md'))
assert skills
for path in skills:
    text = path.read_text(encoding='utf-8')
    assert text.startswith('---\n')
    header = text.split('---', 2)[1]
    assert 'name:' in header
    assert 'description:' in header
print('PHASE_20_SKILLS_OK')
PY
tmp_home="$(mktemp -d)"
for f in .codex/hooks/*.py; do printf '{}' | RALPH_HOME="$tmp_home" PYTHONDONTWRITEBYTECODE=1 python3 "$f" >/dev/null || exit 1; done
tmp_vault="$(mktemp -d)"
VAULT_DIR="$tmp_vault" python3 scripts/vault/vault-init.py
VAULT_DIR="$tmp_vault" python3 scripts/vault/vault-save.py --classification GREEN --text 'Phase 20 acceptance validates vault temporary storage.'
VAULT_DIR="$tmp_vault" python3 scripts/vault/vault-save.py --classification YELLOW --text 'Phase 20 project-scoped vault acceptance note.'
VAULT_DIR="$tmp_vault" python3 scripts/vault/vault-save.py --classification GREEN --text 'redaction fixture value'
VAULT_DIR="$tmp_vault" python3 scripts/vault/vault-search.py 'Phase 20 acceptance validates vault'
VAULT_DIR="$HOME/Documents/Obsidian/MiVault" python3 scripts/vault/vault-search.py '__codex_phase20_readonly_probe_no_match__' || true
tmp_home="$(mktemp -d)"
RALPH_ROOT="$(cat ~/.codex/hooks/.ralph-repo-root)"
RALPH_HOME="$tmp_home" python3 "$RALPH_ROOT/scripts/memory/wakeup.py"
RALPH_HOME="$tmp_home" python3 scripts/memory/handoff.py --summary 'Phase 20 memory handoff acceptance.' --status ok
RALPH_HOME="$tmp_home" python3 scripts/memory/classify-learning.py --text 'redaction fixture value'
python3 scripts/gates/run-gates.py --minimal
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/unit -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/integration -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/evals -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests -q
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/cost_router_v1.yaml --output .ralph-codex/reports/evals/phase20_cost_router_scorecard.json
python3 scripts/evals/research_eval.py --mode mock --output .ralph-codex/reports/evals/phase20_research_eval.json
python3 scripts/evals/vision_eval.py --mode mock --output .ralph-codex/reports/evals/phase20_vision_eval.json
python3 scripts/evals/coding_model_eval.py --mode mock --output .ralph-codex/reports/evals/phase20_coding_model_eval.json
python3 scripts/evals/autoresearch_dry_run.py --output .ralph-codex/reports/evals/phase20_autoresearch.json --jsonl .ralph-codex/reports/evals/phase20_autoresearch_runs.jsonl
mcp__ralph_coding_models__.validate_coding_models
python3 scripts/cost/route-task.py --task-type code_review --complexity 4 --sensitivity green --text 'redaction fixture value'
python3 scripts/cost/redact-for-external.py --json --text 'redaction fixture value'
grep -R "GPT Imágenes 2" AGENTS.md docs/architecture .agents/skills/model-router/SKILL.md
grep -R "Codex main decides\|Codex main owns" AGENTS.md .agents/skills/orchestrator/SKILL.md .agents/skills/model-router/SKILL.md
grep -R "model_provider.*zai\|model_provider.*minimax\|\[model_providers\.zai\]\|\[model_providers\.minimax\]" .codex .agents scripts docs --exclude-dir=__pycache__ || true
git diff --check
```

## MCP Result

`ralph_coding_models.validate_coding_models` returned:

- `glm-5.1`: OK
- `glm-5-turbo`: OK
- `MiniMax-M2.7-highspeed`: OK
- `all_ok`: true

No API keys or environment values were printed.

The current Codex tool registry also exposes Z.ai and MiniMax MCP-backed namespaces used by this repo policy, including `mcp__zai_vision__`, `mcp__minimax_coding_tools__`, `mcp__web_search__`, and `mcp__ralph_coding_models__`.

## Remaining Risks

- The RED detector is intentionally conservative. It can block benign text that references `.env`, customer markers, or credential-shaped examples. That is acceptable for external routing and durable memory paths.
- The acceptance run validated the real Obsidian vault read-only. It did not write to the real vault to avoid creating production memory during acceptance.
- Live Z.ai/MiniMax model validation was performed through `ralph_coding_models`; research, vision, and coding evals used deterministic mock fixtures for repeatable scoring.
- FASE 18, FASE 19, and FASE 20 changes are present in the working tree and still need a final commit/push when approved.

## Next Steps

- Review the pending diff as one final acceptance batch.
- Commit and push after approval.
- Optionally run `bash scripts/setup/install-global.sh --dry-run --with-agents` before a real global install.

Decision: PASS
