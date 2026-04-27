# Threat Model

Primary assets are secrets, credentials, private keys, wallet material, customer data, private vault notes, proprietary code, and raw sensitive logs.

Main risks:

- RED content externalized to MCP tools.
- Secrets printed by hooks or reports.
- Direct provider config added for Z.ai or MiniMax.
- Vault data copied into the public repo.
- Generated content accepted without gates.
- Vision tools used for generation instead of analysis.

Controls:

- Sensitivity classification gates every route.
- RED stays local and is discarded after use.
- No `model_provider directo` for Z.ai or MiniMax.
- Vault scripts skip RED saves.
- Hooks avoid secret printing and fail softly.
- Gates and evals provide evidence before completion.
- Z.ai and MiniMax are analysis-only for vision. GPT Imágenes 2 is the approved visual generation route.

Related phases: [PHASE_03](../migration/checkpoints/PHASE_03.md), [PHASE_05](../migration/checkpoints/PHASE_05.md), [PHASE_07](../migration/checkpoints/PHASE_07.md), [PHASE_10](../migration/checkpoints/PHASE_10.md), [PHASE_15](../migration/checkpoints/PHASE_15.md).

