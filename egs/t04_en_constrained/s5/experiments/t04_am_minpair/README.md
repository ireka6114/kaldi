# T04 AM Minimal-Pair Retraining Scaffold

This directory provides an isolated scaffold for targeted AM adaptation/retraining evaluation on T04 vowel minimal pairs.

## Files
- `config/minpair_experiment.template.json`: experiment config template
- `scripts/generate_t04_minpair_manifests.py`: focused train/dev/eval manifest generator
- `scripts/run_t04_minpair_am_experiment.sh`: one-shot runner (manifest -> adaptation command -> eval)
- `scripts/eval_t04_minpair_am.py`: baseline vs adapted AM comparison
- `docs/t04_am_minpair_retraining_plan.md`: experiment plan and success criteria

## Quick Start
1. Copy and edit config:
```bash
cp egs/t04_en_constrained/s5/experiments/t04_am_minpair/config/minpair_experiment.template.json \
  egs/t04_en_constrained/s5/runtime/diagnostic/minpair_experiment.json
```

2. Set at least:
- `baseline_model_dir`
- `adaptation_command` (optional; if empty, runner symlinks baseline as adapted for dry-run)

3. Run scaffold:
```bash
bash egs/t04_en_constrained/s5/experiments/t04_am_minpair/scripts/run_t04_minpair_am_experiment.sh \
  egs/t04_en_constrained/s5/runtime/diagnostic/minpair_experiment.json
```

## Baseline vs Adapted Eval Only
If you already have adapted model output, run:
```bash
python3 egs/t04_en_constrained/s5/experiments/t04_am_minpair/scripts/eval_t04_minpair_am.py \
  --runtime-root egs/t04_en_constrained/s5/runtime \
  --wav-dir egs/t04_en_constrained/s5/runtime/diagnostic/wavs_ref_renamed_16k \
  --baseline-model-dir /abs/path/to/baseline_model \
  --adapted-model-dir /abs/path/to/adapted_model \
  --experiment-dir egs/t04_en_constrained/s5/runtime/diagnostic/am_minpair_eval_manual
```

## Success Criterion
At least some fixed pairs (`gop/gope`, `vop/vope`, `wot/wote`, `jop/jope`) should move away from `100%` zero phone-level margins, while control pairs (`fot/fote`, `zot/zote`, `jope/jop`) should not regress badly.
