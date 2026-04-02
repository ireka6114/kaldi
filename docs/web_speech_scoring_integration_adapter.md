# Web Speech Scoring Adapter Handoff

## What Was Added
- One unified adapter CLI: `scripts/run_pseudoword_adapter.py`
- One centralized integration config: `config/pseudoword_adapter_config.json`
- One host-facing contract doc: `docs/pseudoword_web_adapter_contract.md`

## Current Operating Mapping
- `T04_EN_DYNAMIC`
  - active business version: `t04_stable_pilot_v1`
  - adapter mode: `formal_single_item`
- `T01_EN_PHONDEL`
  - active set unchanged
  - adapter mode: `formal_single_item`
  - instruction clarification remains metadata-only
- `T02_EN_DYNAMIC_PHONDEL`
  - active set unchanged
  - adapter mode: `formal_single_item`
  - optional suffix preparation exposed through `prepare`
- `T12_ZH_PINYIN`
  - adapter mode now: `shadow_decode_evidence`
  - future path intentionally reserved: `formal_single_item`

## Why T12 Was Implemented This Way
- Current repo truth still supports `decode-evidence` scoring, not direct wav formal scoring.
- The adapter keeps T12 on the same contract as other tasks now, so later formalization only needs a handler/config switch, not a new host integration surface.

## Minimal Integration Sequence
1. Run `check --all` from this repo.
2. Wire the main project Kaldi path to this adapter.
3. Connect `T04` first.
4. Connect `T01/T02` through the same adapter.
5. Keep `T12` on shadow-mode until direct decode is approved.
