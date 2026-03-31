# T04 AM Retraining Plan (Minimal Pairs)

## Scope
This experiment scaffold targets acoustic-model discriminability only.

Fixed short-vs-long pairs (known problematic):
- `gop/gope`
- `vop/vope`
- `wot/wote`
- `jop/jope`

Control pairs (currently separable):
- `fot/fote`
- `zot/zote`
- `jope/jop`

## Hard Constraints
- Do not modify lexicon truth.
- Do not modify phones truth.
- Do not modify graph truth.
- Do not modify scorer decision logic for this experiment phase.
- Retraining/adaptation config must be isolated per experiment directory.

## Data Split Assumptions
Default assumptions in template config:
- `train_reps`: `r1`
- `dev_reps`: `r2`
- `eval_reps`: `r1,r2`
- Source wavs default to `runtime/diagnostic/wavs_ref_renamed_16k`.

If more data is available, expand reps/wav dirs in config only.

## Experiment Flow
1. Generate focused manifests:
- train manifest (`minpair_train_manifest.jsonl`)
- dev manifest (`minpair_dev_manifest.jsonl`)
- eval manifest (`minpair_eval_manifest.jsonl`)
- eval word-set config (`minpair_eval_word_sets.json`)

2. Run adaptation/retraining command (isolated):
- input baseline model dir
- output adapted model dir
- keep command explicit in config (`adaptation_command`)

3. Run baseline vs adapted evaluation on same eval set:
- produce pair-level phone-level margin distributions
- produce zero-margin percentages
- produce decision counts and status-ok rates

## Metrics (Per Pair)
For each pair, report:
- `phone_level_evidence_status` distribution
- `vowel_local_margin_phone_level` distribution
- `% exactly-zero phone-level margins` among status=ok rows
- `accept/reject/uncertain` counts
- baseline vs adapted deltas for zero-margin percentage

## Expected Success Criterion
At least some of the four fixed pairs should no longer have `100%` zero phone-level margins,
while control pairs should not regress badly.

## Output Convention
All run artifacts are written under:
- `runtime/diagnostic/am_minpair_experiments/<experiment_name>_<timestamp>/`

Core outputs:
- manifests/
- eval/baseline and adapted micro-probe outputs
- eval comparison report (`am_minpair_eval_report.json/.md`)
