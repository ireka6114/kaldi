# Local Task Inventory

This document is the single entry point for the custom task work in this fork.
It exists to make task discovery predictable and to avoid having to guess
whether a task has a standalone recipe, a shared core, or only design notes.

## Active task families

### T01/T02 shared English elision core

Implementation root:
- `egs/elision_en_core/s5`

Primary docs:
- `egs/elision_en_core/s5/docs/elision_en_core_design.md`
- `egs/elision_en_core/s5/docs/elision_en_core_summary.md`

Status:
- Implemented as one shared Kaldi-side asset layer: `ELISION_EN_CORE`
- `T01_EN_STATIC` and `T02_EN_DYNAMIC` do not have separate bottom-layer
  dictionaries or graph families
- `T01_EN_STATIC` runs the shared item inventory in fixed order and writes
  `error_item_ids`
- `T02_EN_DYNAMIC` starts from the first wrong `T01` item and runs the
  remaining suffix of that same shared sequence

Shared item inventory:
- `ELISION_A_FOTTING`: `fotting -> ting`, deleted part `fot`
- `ELISION_A_GOPPING`: `gopping -> ping`, deleted part `gop`
- `ELISION_B_WOT`: `wot -> ot`, deleted part `w`
- `ELISION_B_ZOD`: `zod -> od`, deleted part `z`

Probe policy:
- Group `A` items use `syllable_deletion_probe`
- Group `B` items use `phoneme_deletion_probe`

Config files:
- `egs/elision_en_core/s5/config/elision_items.json`
- `egs/elision_en_core/s5/config/elision_probe_sets.json`
- `egs/elision_en_core/s5/config/elision_lexicon_delta.tsv`
- `egs/elision_en_core/s5/config/t01_static_rules.json`
- `egs/elision_en_core/s5/config/t02_dynamic_rules.json`

Important note:
- When looking for `T01` or `T02`, search under `egs/elision_en_core/s5`
  first. They are orchestration layers over a shared-core task, not separate
  `egs/t01_*` or `egs/t02_*` recipes.

### T04 English constrained pseudoword task

Implementation root:
- `egs/t04_en_constrained/s5`

Primary docs:
- `egs/t04_en_constrained/s5/README.md`
- `docs/t04_kaldi_decode_design.md`
- `egs/t04_en_constrained/s5/docs/t04_vowel_probe_maintenance.md`

Status:
- Standalone recipe implemented
- Formal scoring path is `candidate-specific micro-probe scoring`
- `whole-word` modes are retained only for auxiliary analysis

Formal levels and current main items:
- `T04_CVC`: `fot`, `gop`, `vop`, `wot`, `jop`, `zot`
- `T04_CVCE`: `fote`, `gope`, `vope`, `wote`, `jope`, `zote`
- `T04_ING_A`: `fotting`, `goping`, `vopping`, `woting`, `jopping`, `zoting`
- `T04_ING_B`: `fotting`, `gopping`, `vopping`, `wotting`, `jopping`, `zotting`

Probe dimensions:
- `onset_probe`
- `vowel_probe`
- `pattern_probe`

Known fixed-pair watchlist:
- `gop/gope`
- `vop/vope`
- `wot/wote`
- `jop/jope`

Control anchors:
- `fot/fote`
- `zot/zote`
- `jope/jop`

Stimulus redesign status:
- Redesign work exists, but it is still an experiment branch and has not
  replaced the formal recipe config
- Redesign docs live under
  `egs/t04_en_constrained/s5/experiments/t04_stimulus_redesign/docs`
- Current replacement candidates include `bop/bope`, `kop/kope`, `kot/kote`,
  and `zop/zope`

Config files:
- `egs/t04_en_constrained/s5/config/t04_word_sets.json`
- `egs/t04_en_constrained/s5/config/t04_confusion_sets.json`
- `egs/t04_en_constrained/s5/config/t04_ipa_pron_map.csv`

### T12 Mandarin pinyin task

Implementation root:
- `egs/t12_zh_pinyin/s5`

Primary docs:
- `egs/t12_zh_pinyin/s5/README.md`
- `docs/t12_zh_pinyin_status.md`

Status:
- Standalone recipe implemented
- Uses the Mandarin `multi_cn` M11 online model assets
- Formal graphs and probe graphs are generated
- Micro-probe scoring from decode evidence JSON is implemented
- Engine / shadow-mode integration is still pending

Formal level:
- `T12_FORMAL`

Current formal item inventory:
- `dao4`, `gui1`, `qie1`, `jiu4`, `dun1`, `wen2`, `ying3`, `xue3`
- `hua1`, `lai4`, `ban2`, `cui2`, `diao2`, `guai2`, `jue3`, `kong2`
- `luan1`, `mei1`, `xiu2`, `yue2`, `zu4`, `ce2`, `diu4`, `fou2`
- `gei4`, `kuo3`, `keng4`, `nin4`, `nue3`, `te2`, `hei4`, `run1`

Probe dimensions:
- `onset_probe`
- `final_probe`
- `tone_probe`

Config files:
- `egs/t12_zh_pinyin/s5/config/t12_items_master.csv`
- `egs/t12_zh_pinyin/s5/config/t12_word_sets.json`
- `egs/t12_zh_pinyin/s5/config/t12_confusion_sets.json`
- `egs/t12_zh_pinyin/s5/config/t12_display_to_token.tsv`

Important note:
- T12 is not built from the T04 English model and should not be documented as a
  T04 variant.

## Not currently implemented as standalone local tasks

The following names do not currently have their own standalone task recipes in
this repository:
- `T01` as a separate `egs/t01_*` directory
- `T02` as a separate `egs/t02_*` directory

Their implemented form is the shared `ELISION_EN_CORE` described above.

## Maintenance rule

When adding a new custom task or changing the structure of an existing one,
update this file together with the task-local README or status doc in the same
change.
