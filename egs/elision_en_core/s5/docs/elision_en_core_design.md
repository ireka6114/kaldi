# ELISION_EN_CORE Design

`ELISION_EN_CORE` is the shared Kaldi-side asset layer for the English elision item set.

Implementation summary and produced artifacts are tracked separately in `docs/elision_en_core_summary.md`.

It serves two task flows:

- `T01_EN_STATIC`: a static assessment flow that runs the shared item inventory and produces `error_item_ids`.
- `T02_EN_DYNAMIC`: a dynamic teaching flow that starts at the first wrong item in the `T01_EN_STATIC` order, then continues through the remaining suffix of the shared item sequence while reusing the same underlying probes, scoring, dictionary, language model assets, and graphs.

## Shared-core boundary

The following assets are shared by both `T01_EN_STATIC` and `T02_EN_DYNAMIC`:

- `dict_ELISION_EN`
- `lang_elision_en`
- item inventory
- shared lexicon delta
- probe manifest
- graph manifest
- scoring engine
- model manifest
- probe health check
- micro-probe JSON generator
- T04 compiler bridge for micro-graphs

`T02_EN_DYNAMIC` is not a separate acoustic task definition. Its dynamic behavior comes from orchestration and pedagogy rules, not from a second Kaldi dictionary or a duplicated graph family.

## Configuration split

- `config/elision_items.json`: canonical item truth for the shared elision item set.
- `config/elision_probe_sets.json`: per-item deletion probe definitions.
- `config/elision_lexicon_delta.tsv`: the manually maintained lexicon increment for shared-core surfaces. It is the single source for shared lexical additions and must not be forked into separate `T01` and `T02` copies.
- `config/t01_static_rules.json`: ordering, termination, and record policy for `T01_EN_STATIC`.
- `config/t02_dynamic_rules.json`: retry, prompt, feedback, teaching metadata, and the rule that `T02_EN_DYNAMIC` begins from the first `T01` error item and continues to the end.

## Lexicon delta mechanism

`dict_ELISION_EN` is generated from a shared lexicon delta, not by manually editing the merged main lexicon files.

- Manual source: `config/elision_lexicon_delta.tsv`
- Generated increment: `runtime/lang/dict_ELISION_EN/lexicon.delta.txt`
- Generated merged outputs: `runtime/lang/dict_ELISION_EN/lexicon.txt` and `runtime/lang/dict_ELISION_EN/lexiconp.txt`

The dictionary build step validates:

- every shared-core `whole_word`, `target_word`, and `deleted_part` surface required by the item inventory exists in the delta file
- target phones are the suffix remainder of the whole-word phones after deletion
- deleted-part phones are the matching prefix of the whole-word phones
- every surface is unique in the delta file
- `B`-group pseudo-words use manually specified phones from the delta file and do not use automatic G2P

`T01_EN_STATIC` and `T02_EN_DYNAMIC` share the same lexicon delta. Duplicating or forking separate delta files for the two flows is not allowed.

## Probe policy

- Group `A`: first-syllable deletion probes use `target_word` as the remaining form, with `whole_word` and `deleted_part` as competitors.
- Group `B`: first-phoneme deletion probes use `target_word` as the remaining form, with `whole_word` as the default competitor. Deleted-part-only comparison is left disabled by default.

## Graph policy

Every graph in the shared manifest declares:

- `applicable_tasks: ["T01_EN", "T02_EN"]`
- `task_mode: "shared_core"`
- `group`
- `probe_type`

First version policy: no duplicate `T02`-specific bottom-layer graph family is created.

## Micro-probe JSON

Single-item micro-probe configs can be generated from the shared-core inventory.

- generator: `scripts/generate_micro_probe_json.py`
- example output: `runtime/diagnostic/q09_let_style_example.json`

The intended shape is:

```json
{
  "item": "q09_let",
  "probe_type": "phoneme_deletion_probe",
  "target": "__et__",
  "competitors": ["let"]
}
```

In the shared-core implementation, the same shape is produced from the canonical item and probe definitions, with optional helper metadata added for bridge scripts.

## T04 compiler reuse

Micro-graph compilation can reuse the existing T04 compiler path instead of introducing a second compiler implementation.

- bridge script: `scripts/build_micro_probe_via_t04.sh`
- reused compiler steps:
- `egs/t04_en_constrained/s5/scripts/build_t04_grammars.sh`
- `egs/t04_en_constrained/s5/scripts/build_t04_graphs.sh`

The bridge works by translating a shared-core micro-probe JSON into temporary T04-compatible config files, then delegating grammar and graph compilation to the existing T04 scripts.

This keeps the compilation mechanism aligned with the already-tested T04 micro-graph path while preserving the shared-core asset model for `T01_EN_STATIC` and `T02_EN_DYNAMIC`.

## Verification

The current shared-core design has been exercised with:

- shared dict/lang build
- shared grammar and graph build
- manifest inspection
- probe health check on small human-audio samples
- micro-probe JSON generation
- T04 bridge compilation for a sample micro-probe

## Main-project integration

Future host-project integration should preserve this division:

- `T01_EN_STATIC` produces `error_item_ids`.
- `T02_EN_DYNAMIC` maps `error_item_ids` onto the fixed `T01` order, starts from the first wrong item, and runs the remaining suffix to completion.
- The dynamic layer may vary prompt levels, feedback, and retry strategy, but it should continue to call the same shared Kaldi probe graphs and the same shared scoring engine.
