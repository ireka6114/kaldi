# Web Speech Scoring Integration Readiness

## Scope
- Current runtime target: WSL2-local Kaldi workspace at `/home/yoeseka/kaldi`
- Integration target: host web speech-scoring project invoking a unified adapter instead of task-local scorer scripts

## Current Readiness Summary
- `T04`: adapter-ready in `formal_single_item` mode with stable-pilot business source `t04_stable_pilot_v1` and a passing smoke run.
- `T01/T02`: adapter-ready in `formal_single_item` mode with shared-core structure preserved and instruction clarification carried as metadata.
- `T12`: adapter-ready in `shadow_decode_evidence` mode with a reserved future upgrade path to `formal_single_item`.

## What Is Now Ready
- Unified host-facing adapter exists:
  - `scripts/run_pseudoword_adapter.py`
- Centralized adapter config exists:
  - `config/pseudoword_adapter_config.json`
- Host-facing contract doc exists:
  - `docs/pseudoword_web_adapter_contract.md`
- Readiness self-check passes across `T04`, `T01/T02`, and `T12`:
  - `runtime/diagnostic/pseudoword_adapter_readiness_check.json`
- Real smoke runs have been captured for:
  - `T04_EN_DYNAMIC`
  - `T01_EN_PHONDEL`
  - `T02_EN_DYNAMIC_PHONDEL`
  - `T12_ZH_PINYIN` shadow mode

## Remaining Integration Boundaries
- Adapter is designed to run inside the same WSL environment as this repo.
- Returned artifact paths are debug-only and should not become host business dependencies.
- `T12` direct wav formal mode is intentionally not enabled yet; it remains on decode-evidence shadow mode until formal promotion is approved.
- `T04` direct-audio path is now adapter-owned and smoke-tested, but still depends on current local Kaldi runtime/model assets being present.

## Practical Integration Interpretation
- Main web project can now integrate through one stable adapter contract instead of per-task scripts.
- `T04` should be integrated first as the primary formal pseudoword task.
- `T01/T02` can follow through the same adapter without task-structure changes.
- `T12` can be connected immediately for shadow monitoring, and later promoted without changing the top-level host contract.

## Current Go/No-Go
- `T04`: go for adapter-layer integration.
- `T01/T02`: go for adapter-layer integration.
- `T12`: go for shadow-mode adapter integration now; future formal-mode promotion is pre-shaped but not yet enabled.
