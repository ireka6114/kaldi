# ELISION_EN_CORE Summary

This document summarizes the shared-core Kaldi work completed under `egs/elision_en_core/s5`.

## Outcome

`T01_EN_STATIC` and `T02_EN_DYNAMIC` now share one Kaldi-side core instead of maintaining separate bottom-layer assets.

Implemented shared assets:

- shared dictionary: `dict_ELISION_EN`
- shared lang directory: `lang_elision_en`
- shared item inventory
- shared probe manifest
- shared graph manifest
- shared scoring engine
- shared model manifest
- shared probe health check

The shared runtime manifests are:

- `runtime/manifests/elision_graph_manifest.json`
- `runtime/manifests/elision_probe_manifest.json`
- `runtime/manifests/elision_model_manifest.json`

## T01 and T02 boundary

- `T01_EN_STATIC` runs the shared item set in fixed order and writes `error_item_ids`.
- `T02_EN_DYNAMIC` does not create a second dictionary or graph family.
- `T02_EN_DYNAMIC` starts from the first wrong `T01` item and continues through the remaining suffix of the same shared sequence.
- Dynamic behavior stays in configuration and orchestration metadata, not in a separate acoustic-task definition.

Relevant outputs:

- `runtime/diagnostic/t01_static_trials.json`
- `runtime/diagnostic/t01_static_results.json`
- `runtime/diagnostic/t01_error_item_ids.json`
- `runtime/diagnostic/t02_dynamic_trials.json`

## Lexicon delta mechanism

The dictionary is now generated through a shared lexicon increment mechanism rather than by manually editing the merged main lexicon.

Implemented files:

- manual delta source: `config/elision_lexicon_delta.tsv`
- generated delta lexicon: `runtime/lang/dict_ELISION_EN/lexicon.delta.txt`
- generated merged lexicon: `runtime/lang/dict_ELISION_EN/lexicon.txt`
- generated merged weighted lexicon: `runtime/lang/dict_ELISION_EN/lexiconp.txt`

Current validation rules in the build step:

- every shared-core `whole_word`, `target_word`, and `deleted_part` surface must be present in the delta file
- all surfaces must be unique in the delta file
- target phones must match the whole-word suffix after deletion
- deleted-part phones must match the deleted whole-word prefix
- `B`-group pseudo-words must use manually supplied phones from the delta file
- no automatic G2P is used for `B`-group pseudo-words

`T01_EN_STATIC` and `T02_EN_DYNAMIC` share the same lexicon delta. Copying or forking separate delta files for the two task flows is not allowed.

## Micro-probe support

Single-item micro-probe JSON generation is available.

Implemented script:

- `scripts/generate_micro_probe_json.py`

Example output:

- `runtime/diagnostic/q09_let_style_example.json`

This produces configs in the form:

```json
{
  "item": "elision_b_wot",
  "probe_type": "phoneme_deletion_probe",
  "target": "__ot__",
  "competitors": ["wot"]
}
```

## Reuse of T04 graph compiler

Shared-core micro-graph compilation can reuse the existing T04 compilation path.

Implemented bridge:

- `scripts/build_micro_probe_via_t04.sh`

What it does:

- reads a shared-core micro-probe JSON
- translates it into temporary T04-compatible config files
- directly calls `egs/t04_en_constrained/s5/scripts/build_t04_grammars.sh`
- directly calls `egs/t04_en_constrained/s5/scripts/build_t04_graphs.sh`

Example compiled outputs:

- `runtime/manifests/q09_let_style_example_graph_manifest.json`
- `runtime/manifests/q09_let_style_example_probe_manifest.json`

## Verification status

The shared-core build chain has been exercised end to end:

- `scripts/build_elision_lang.sh`
- `scripts/build_elision_grammars.sh`
- `scripts/build_elision_graphs.sh`
- `scripts/inspect_elision_graphs.sh`
- `scripts/check_elision_probe_health.py`

Probe-health output:

- `runtime/diagnostic/elision_probe_health_report.json`
- `runtime/diagnostic/elision_probe_health_report.md`

Current status at the time of writing:

- shared manifest inspection passes
- shared dict/lang/probe/graph assets are generated successfully
- small human-audio probe health check passes

## Practical interpretation

The current repository state is ready for a host project to:

- call `T01_EN_STATIC` to obtain `error_item_ids`
- pass control to `T02_EN_DYNAMIC`
- let `T02_EN_DYNAMIC` start at the first wrong `T01` item and continue to the end
- keep using the same shared lexical, probe, graph, and scoring assets throughout
