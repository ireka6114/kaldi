# T04 `vowel_probe` 维护说明

本文档记录 `score_t04_micro_probes.py` 中 `vowel_probe` 的当前正式实现、字段语义和回归维护方法（Phase 2：phone-level 局部打分版）。

## 1. 判决逻辑（当前版本）

`vowel_probe` 采用四层判决链：

1. phone-level 元音 margin 主判  
2. phone-level 元音帧长比辅判  
3. 旧 local proxy（仅在 phone-level 不可用时）  
4. 整词 margin 兜底（局部不可用或与整词强冲突时）

关键实现位置：

- `build_vowel_local_evidence(...)`
- `score_one_probe(...)`
- `score_vowel_pair_phone_level(...)`（独立 helper）

文件：

- `/home/yoeseka/kaldi/egs/t04_en_constrained/s5/scripts/score_t04_micro_probes.py`
- `/home/yoeseka/kaldi/egs/t04_en_constrained/s5/scripts/t04_phone_level_scoring.py`

说明：

- 当前主路径已是 `target/competitor` 独立强制对齐后 phone-level 计分。
- `target_vowel_acoustic_cost` / `competitor_vowel_acoustic_cost` 来自 `nnet3-align-compiled --write-per-frame-acoustic-loglikes` 的元音核帧累计。
- 若 phone-level 不可用，`local_score_mode=proxy_from_probe_total_cost_per_frame` 时才会回落到旧 proxy。

## 2. 单对调试（先验证再集成）

脚本：

- `/home/yoeseka/kaldi/egs/t04_en_constrained/s5/scripts/debug_t04_vowel_phone_level.py`

示例：

```bash
python3 /home/yoeseka/kaldi/egs/t04_en_constrained/s5/scripts/debug_t04_vowel_phone_level.py \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime \
  --wav-path /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/wavs_ref_renamed_16k/cvc_gop_r1.wav \
  --target-word gop \
  --competitor-word gope
```

控制台应至少看到：

- `target_vowel_acoustic_cost`
- `competitor_vowel_acoustic_cost`
- `target_vowel_frames`
- `competitor_vowel_frames`
- `vowel_local_margin`

## 3. CSV 关键字段（维护必看）

`t04_micro_probe_results*.csv` 对 `vowel_probe` 重点关注：

- `local_score_mode`
- `phone_level_evidence_status`
- `target_vowel_acoustic_cost`
- `competitor_vowel_acoustic_cost`
- `target_vowel_avg_cost_per_frame`
- `competitor_vowel_avg_cost_per_frame`
- `vowel_local_margin_phone_level`
- `target_vowel_frames_phone_level`
- `competitor_vowel_frames_phone_level`
- `target_vowel_cost_source`
- `competitor_vowel_cost_source`
- `decision_detail`

兼容字段（旧逻辑保留）：

- `vowel_local_margin`
- `local_duration_ratio`
- `local_margin_source`
- `local_duration_source`

## 4. `decision_detail` 语义

- `phone_level_margin_win`: phone-level margin 超阈值直接判定
- `phone_level_duration_win`: phone-level margin 不够，靠 phone-level 帧长比判定
- `local_margin_win`: 回退到旧 local proxy 后由局部 margin 判定
- `local_duration_win`: 回退到旧 local proxy 后由局部时长判定
- `whole_word_fallback`: 局部不可用或与整词强冲突，回退整词判定
- `uncertain_close_call`: 局部证据存在但接近
- `uncertain_no_evidence`: 局部/整词关键证据缺失

## 5. 回归命令

```bash
python3 /home/yoeseka/kaldi/egs/t04_en_constrained/s5/scripts/score_t04_micro_probes.py \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime \
  --wav-dir /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/wavs_ref_renamed_16k \
  --output-json /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/t04_micro_probe_results_ref_renamed.json \
  --summary-json /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/t04_micro_probe_summary_ref_renamed.json \
  --output-csv /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/t04_micro_probe_results_ref_renamed.csv
```

summary 里额外检查：

- `vowel_probe_phone_level_evidence_status_distribution`
- `vowel_probe_decision_detail_distribution`
- `vowel_probe_fixed_pair_phone_level_margin_stats`

## 6. 维护检查清单

每次改动后至少检查：

1. `local_score_mode` 中 `forced_align_phone_level` 是否为主。
2. `phone_level_evidence_status` 是否出现异常退化（大量非 `ok`）。
3. 固定 pair：`gop/gope`, `vop/vope`, `wot/wote`, `jop/jope` 的 `vowel_local_margin_phone_level` 是否仍为 0。
4. 原可分 pair：`fot/fote`, `zot/zote`, `jope/jop` 是否被破坏。

## 7. 禁止项

维护中禁止通过词典真值 hack 追求表面区分：

- 不改 `lexiconp.txt` 真值映射
- 不人为重复 phone 制造状态差
- 不插入弱元音占位 phone

如需做此类实验，只能放实验分支，不进正式主线。
