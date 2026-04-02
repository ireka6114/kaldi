# Pseudoword Web Adapter Contract

## Purpose
- Provide one host-facing entrypoint for pseudoword-related tasks in this repo.
- Keep task-local scorers and manifests unchanged.
- Hide WSL-local absolute paths and task-specific orchestration behind one JSON CLI contract.

## Command
```bash
python3 scripts/run_pseudoword_adapter.py run --request-json <request.json> --output-json <response.json>
```

## Unified Request Shape
```json
{
  "task_code": "T04_EN_DYNAMIC",
  "request_id": "req_001",
  "item_id": "gepe",
  "target_word": "gepe",
  "audio_wav_path": "/abs/path/item.wav",
  "audio_b64": null,
  "decode_evidence_json": null,
  "decode_evidence_items": null,
  "context": {
    "phase": "formal",
    "error_item_ids": [],
    "group_name": null,
    "teaching_level": null
  },
  "options": {
    "desired_mode": "formal"
  }
}
```

## Unified Response Shape
Top-level fields intentionally mirror the main web scoring flow.

```json
{
  "ok": true,
  "request_id": "req_001",
  "task_code": "T04_EN_DYNAMIC",
  "item_id": "gepe",
  "engine": "kaldi_wfst",
  "mode": "formal",
  "score_source": "kaldi_wfst",
  "asr_transcript": "gepe",
  "is_correct": true,
  "item_score": 1.0,
  "confidence": 0.92,
  "source": "pseudoword_adapter_v1",
  "fallback_reason": null,
  "extra": {
    "kaldi_wfst": {}
  }
}
```

## Task-Specific Input Rules
- `T04_EN_DYNAMIC`
  - Current mode: `formal_single_item`
  - Required: `target_word` or `item_id`, plus `audio_wav_path` or `audio_b64`
  - Uses current business source: `runtime/diagnostic/t04_stable_pilot_v1_manifest.json`
- `T01_EN_PHONDEL`
  - Current mode: `formal_single_item`
  - Required: `item_id`, plus `audio_wav_path` or `audio_b64`
  - Instruction clarification is metadata-only; no scorer change
- `T02_EN_DYNAMIC_PHONDEL`
  - Current mode: `formal_single_item`
  - Required: `item_id`, plus `audio_wav_path` or `audio_b64`
  - Dynamic suffix preparation is exposed separately through `prepare`
- `T12_ZH_PINYIN`
  - Current mode: `shadow_decode_evidence`
  - Required now: `decode_evidence_json` or `decode_evidence_items`
  - Current direct-wav formal mode is not enabled yet
  - The adapter contract is intentionally already future-compatible with a later `formal_single_item` switch

## T12 Future Formal-Mode Compatibility
- Keep the same top-level request/response contract.
- Later formal promotion should only require:
  - adding direct decode handling inside the adapter
  - flipping `current_host_mode` in `config/pseudoword_adapter_config.json`
- Host-side callers should already pass `options.desired_mode`; current T12 will reject `formal` with a structured `unsupported_current_mode` response instead of requiring a new interface.

## Readiness and Preparation Commands
```bash
python3 scripts/run_pseudoword_adapter.py check --all --output-json runtime/diagnostic/pseudoword_adapter_readiness_check.json
python3 scripts/run_pseudoword_adapter.py prepare --task T01_EN_PHONDEL --wav-root <wav_root> --output-json <trial_manifest.json>
python3 scripts/run_pseudoword_adapter.py prepare --task T02_EN_DYNAMIC_PHONDEL --wav-root <wav_root> --error-item-ids <error_ids.json> --output-json <trial_manifest.json>
```

## Integration Notes For The Main Web Project
- Main project should call the adapter instead of task-local Kaldi scripts directly.
- The adapter should run inside the same WSL environment as this repo.
- Returned artifact paths are debug-only and must not become host business dependencies.
- Task business versions remain owned by task manifests, not by the host.
