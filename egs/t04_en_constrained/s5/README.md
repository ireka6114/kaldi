# T04_EN Kaldi + WFST 实现总览

本目录是当前已落地的 `T04_EN` 题目实现（Kaldi + WFST）。
后续其他题目请复用同一工程骨架，不要在这里混写新题逻辑。

## 1. 目录分工
- `config/`
  - `t04_word_sets.json`: 题目词集与 level 定义
  - `t04_confusion_sets.json`: confusion family 与策略配置
  - `t04_ipa_pron_map.csv`: 发音映射辅助配置
- `scripts/`
  - 构建链路：`build_t04_lang.sh` / `build_t04_grammars.sh` / `build_t04_graphs.sh` / `inspect_t04_graphs.sh`
  - 诊断链路：`run_t04_diagnostic_experiment.py` / `score_t04_micro_probes.py`
  - phone-level 局部打分：`t04_phone_level_scoring.py` / `debug_t04_vowel_phone_level.py`
  - 体检链路：`check_t04_probe_health.py`
  - 数据准备：`generate_t04_tts_batch.py` / `generate_t04_espeak_ipa_audio.py`
- `runtime/`
  - `lang/`, `lang_graphs/`, `graphs/`: Kaldi/WFST 运行资产
  - `manifests/`: graph/probe/model manifest
  - `diagnostic/`: 诊断结果、体检报告、测试音频

## 2. 当前正式评分口径（T04_EN）
- 正式主路径：`micro-probe scoring`（candidate-specific）
- 主判据：`probe-local raw margin`
- `onset_probe`: raw margin 直接判定
- `vowel_probe`: `phone-level 强制对齐局部元音证据` 主判 + 局部时长辅判 + 兜底
- `pattern_probe`: raw margin + duration fallback（二级证据）
- `level_all` / `family_safe whole-word`: 辅助分析，不作正式默认评分

详细设计请看：
- [t04_kaldi_decode_design.md](/home/yoeseka/kaldi/docs/t04_kaldi_decode_design.md)
- [t04_vowel_probe_maintenance.md](/home/yoeseka/kaldi/egs/t04_en_constrained/s5/docs/t04_vowel_probe_maintenance.md)

## 3. 常用命令
```bash
cd /home/yoeseka/kaldi

./egs/t04_en_constrained/s5/scripts/build_t04_lang.sh
./egs/t04_en_constrained/s5/scripts/build_t04_grammars.sh
./egs/t04_en_constrained/s5/scripts/build_t04_graphs.sh
./egs/t04_en_constrained/s5/scripts/inspect_t04_graphs.sh

python3 egs/t04_en_constrained/s5/scripts/check_t04_probe_health.py \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime \
  --wav-dir /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/wavs_human_16k

python3 egs/t04_en_constrained/s5/scripts/debug_t04_vowel_phone_level.py \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime \
  --wav-path /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/wavs_ref_renamed_16k/cvc_gop_r1.wav \
  --target-word gop \
  --competitor-word gope

python3 egs/t04_en_constrained/s5/scripts/score_t04_micro_probes.py \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime \
  --wav-dir /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/wavs_human_16k \
  --small-margin-threshold 0.05 \
  --duration-threshold 1.2
```

## 4. 后续新题开发约束
1. 新题请新建 `egs/<task_name>/s5`，不要复用 `t04_*` 文件名。
2. 保持同样目录结构：`config/ scripts/ runtime/`。
3. 每个新题必须有独立：
   - `*_word_sets.json`
   - `*_confusion_sets.json`
   - `*_graph_manifest.json`
   - `*_probe_manifest.json`
4. 每个新题必须先跑 `probe health check`，再跑正式诊断。
5. 不跨题复用同一诊断 summary 文件名，避免结果覆盖。
