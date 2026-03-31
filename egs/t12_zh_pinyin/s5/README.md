# T12_ZH_PINYIN Kaldi + WFST Skeleton

`T12_ZH_PINYIN` is a standalone Mandarin pinyin-reading task scaffolded from the `T04_EN` pipeline shape.
Keep all Chinese-specific logic here. Do not mix it into `t04_*`.

## Layout
- `config/`
  - `t12_items_master.csv`: task master table for formal items and probe templates
  - `t12_word_sets.json`: formal level graphs
  - `t12_confusion_sets.json`: optional item-aware bundles
  - `t12_display_to_token.tsv`: display-form to decode-token mapping (`yué -> yue2`)
- `scripts/`
  - `register_t12_m11_assets.py`
  - `build_t12_m11_dict.sh`
  - `build_t12_lang.sh`
  - `build_t12_grammars.sh`
  - `build_t12_graphs.sh`
  - `inspect_t12_graphs.sh`
  - `score_t12_micro_probes.py`
  - `t12_generate_registry.py`
  - `generate_t12_dict_template.py`
- `runtime/`
  - generated `lang/`, `grammar/`, `lang_graphs/`, `graphs/`, `manifests/`
  - local template dict output under `runtime/dict_T12_ZH_PINYIN_template/`

## Design Constraints
- Use a Mandarin model and Mandarin phone symbol table. Do not reuse the English `T04_EN` model.
- Keep `surface_form` and backend `word_id` separate.
- Treat tone as a first-class diagnostic dimension at token/probe level.
- Keep `word_id` tone-marked (`dao4`) and keep `phone_sequence` tone-free (`d ao`).
- Normalize `ue`-family finals to `ve` in intermediate phones (`x ve`, `j ve`, `n ve`, `y ve`).
- Keep formal items and diagnostic-only probe candidates in the same T12 dictionary when building graphs.

## Master Table Contract
`config/t12_items_master.csv` is the source of truth for:
- `surface_form`: UI-facing form, usually with tone marks
- `word_id`: backend ID, stable ASCII, usually numbered-tone form
- `phone_sequence`: tone-free Mandarin phoneset template, mapped to model phoneset before build
- `onset_probe_words`
- `final_probe_words`
- `tone_probe_words`

Probe columns may include diagnostic-only IDs such as `dao1` or `tao4`. Those IDs must exist in the T12 Mandarin lexicon before `lang`/graph build.

## Typical Flow
```bash
cd /home/yoeseka/kaldi

python3 egs/t12_zh_pinyin/s5/scripts/register_t12_m11_assets.py \
  --model-dir /home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved

./egs/t12_zh_pinyin/s5/scripts/build_t12_m11_dict.sh

./egs/t12_zh_pinyin/s5/scripts/build_t12_lang.sh
./egs/t12_zh_pinyin/s5/scripts/build_t12_grammars.sh
./egs/t12_zh_pinyin/s5/scripts/build_t12_graphs.sh
./egs/t12_zh_pinyin/s5/scripts/inspect_t12_graphs.sh
```

`build_t12_lang.sh` uses `prepare_lang.sh --phone-symbol-table` when `runtime/manifests/model_paths.env`
provides `T12_PHONES_TXT`, so T12 must match the registered M11 phoneset exactly.

## Current Scope
This skeleton now ships:
- a T12 master-table driven dict generator
- M11 asset registration into `runtime/manifests/`
- strict M11 `phones.txt` compatibility hooks for `prepare_lang.sh`
- downloaded and resolved official Kaldi Multi_CN M11 online assets under `runtime/model/m11_resolved`
- a runnable `dict_T12_ZH_PINYIN_m11/`
- a runnable `lang_t12/`
- generated formal + micro-probe graph assets under `runtime/graphs/`
- graph manifest with stable `graph_status` field
- graph/probe consistency inspect script
- micro-probe scoring script from decode evidence JSON

Still pending:
- engine shadow-mode integration

## Scoring Input Contract
`score_t12_micro_probes.py` expects a decode evidence JSON list. Each item may include:

```json
[
  {
    "utterance_id": "utt_0001",
    "target_word": "dao4",
    "parent_level_graph": "T12_FORMAL",
    "probe_costs": {
      "T12_PROBE_T12_FORMAL_dao4_ONSET": {
        "dao4": 114.2,
        "tao4": 122.6,
        "gao4": 130.8
      }
    }
  }
]
```

Fallback: if `probe_costs[graph_name]` is absent, it uses top-level `candidate_raw_costs`.

Example:
```bash
python3 egs/t12_zh_pinyin/s5/scripts/score_t12_micro_probes.py \
  --decode-evidence-json egs/t12_zh_pinyin/s5/runtime/diagnostic/t12_probe_decode_evidence.json
```
