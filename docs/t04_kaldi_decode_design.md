# T04_EN Kaldi Diagnostic Design (Micro-Probe First)

关联文档：
- T04_EN 工程入口：[README.md](/home/yoeseka/kaldi/egs/t04_en_constrained/s5/README.md)
- 新题扩展指南：[kaldi_wfst_topic_extension_guide.md](/home/yoeseka/kaldi/docs/kaldi_wfst_topic_extension_guide.md)

## 1) 目标与结论（2026-03-29）
- 正式诊断路径已从 `whole-word free competition` 切换为 `candidate-specific constrained scoring`。
- `whole-word`（`family_safe` / `level_all`）保留为辅助分析，不再作为正式默认评分主路径。
- 正式诊断分数优先来自 `micro-probe`（`onset_probe` / `vowel_probe` / `pattern_probe`）。

## 2) 当前目录与产物
- 脚本目录：`/home/yoeseka/kaldi/egs/t04_en_constrained/s5/scripts`
- 配置目录：`/home/yoeseka/kaldi/egs/t04_en_constrained/s5/config`
- 运行目录：`/home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime`
- 设计文档：`/home/yoeseka/kaldi/docs/t04_kaldi_decode_design.md`

关键 manifest：
- `runtime/manifests/t04_graph_manifest.json`
- `runtime/manifests/t04_probe_manifest.json`

关键诊断输出：
- `runtime/diagnostic/t04_diag_summary.json`（whole-word 对照）
- `runtime/diagnostic/t04_probe_health_report.json`
- `runtime/diagnostic/t04_probe_health_report.md`
- `runtime/diagnostic/t04_micro_probe_results.json`
- `runtime/diagnostic/t04_micro_probe_summary.json`
- `runtime/diagnostic/t04_micro_probe_results.csv`

## 3) 诊断策略切换原则
1. 不废弃原有自由解码链路：`level_all` 仍保留用于 baseline/混淆观察。
2. 正式评分主路径是 `candidate-specific micro-probe`。
3. `onset` 与 `vowel_length` 不在同一个默认 probe 内混判。
4. 正式默认判据改为 `probe-local raw margin`（或等价 log-like margin）：
   `raw_margin = best_competitor_cost - target_cost`。
5. `global normalized_score_per_frame` 仅保留为辅助日志字段，不作正式主判据。
6. uncertainty 基于 `raw_margin` 阈值，而非全局 per-frame 差值。
7. `raw_margin` 只允许在同一音频、同一 probe、同一 acoustic scale 内比较，不跨 probe 解释绝对值。

## 4) Micro-Probe 设计
脚本：`scripts/t04_generate_registry.py`

为每个 T04 formal item 生成 probe（按可用性）：
- `onset_probe`：
  - CVC/CVCE/ING 按同层 `confusion_groups` 构造
  - 例：`fot -> [fot,wot,zot]`，`gop -> [gop,vop,jop]`
- `vowel_probe`：
  - CVC 与 CVCE 成对
  - 例：`fot -> [fot,fote]`，`gope -> [gope,gop]`
- `pattern_probe`：
  - ING 双写/非双写成对
  - 例：`fotting -> [fotting,foting]`，`gopping -> [gopping,goping]`

## 5) Probe Manifest 字段
`runtime/manifests/t04_probe_manifest.json` 至少包含：
- `target_word`
- `probe_type`
- `candidate_words`
- `graph_path`
- `lang_graph_path`
- `diagnostic_dimension`
- `is_formal_probe`

并补充：
- `graph_name`
- `parent_level_graph`
- `diagnostic_dimension_hint`
- `candidate_policy`（`candidate_specific_micro_probe`）

## 6) Probe 体检与根因确认（必须先做）
脚本：`scripts/check_t04_probe_health.py`

最小 probe 集：
- `fot vs fote`
- `gop vs gope`
- `fotting vs foting`
- `gopping vs goping`

体检项：
1. lexicon phone 序列是否不同
2. 编译后 graph 是否包含 target/competitor 分叉
3. 对齐中是否能观察到 phone/span 差异
4. score extraction 是否在比较独立候选假设（target vs competitor）
5. raw_margin=0 的最可能根因归类

当前体检结论（2026-03-30）：
- 4/4 probe 均满足“词典可区分 + 图可分叉 + 假设独立可比较”。
- 4/4 probe 均出现 `raw_margin=0`，且可观察到局部 phone 差异。
- 因此 raw_margin=0 在当前阶段更可能来自“局部差异被当前评分口径淹没/不敏感”，而非“词典或图未区分”。

## 7) 评分实现（第二版：Raw Margin 主判据 + Duration Fallback）
脚本：`scripts/score_t04_micro_probes.py`

逐条音频、逐个 probe 执行 constrained decode，输出：
- `best_candidate`
- `target_cost`
- `best_competitor_cost`
- `raw_margin`
- `margin_threshold`
- `small_margin_threshold`
- `runner_up_candidate`
- `local_evidence_summary`
- `derived_candidate_posterior`（仅 probe 闭集内由路径分数 softmax 近似）
- `aux_normalized_score_per_frame`（辅助字段）
- `phone_alignment_available`
- `diagnostic_phone_span_available`
- `phone_alignment_summary`
- `arc_post_available`
- `arc_post_summary`
- `target_phone_span_frames`
- `competitor_phone_span_frames`
- `duration_ratio`
- `diagnostic_span_start`
- `diagnostic_span_end`
- `duration_decision`
- `duration_threshold`
- `duration_fallback_triggered`
- `diagnostic_dimension_hint`

phone-level evidence（可用则输出）：
- `lattice-align-phones`
- `lattice-arc-post`
- `lattice-to-ctm-conf`（补充）

说明：
- `lattice-to-post` 产生的是 per-frame transition-id posterior，不是直接 word posterior。
- 候选 posterior 如需输出，仅在 micro-probe 闭集内基于路径 raw cost 做近似 softmax，并显式标注为 derived candidate posterior。
- `onset_probe` 保持 raw_margin 主判据。
- `vowel_probe / pattern_probe` 使用两级判定：
  - 一级：raw_margin
  - 二级：仅当 `abs(raw_margin) < small_margin_threshold` 时触发 duration fallback
- duration fallback 是二级证据，不会无条件覆盖一级判定；证据不足时保持 `uncertain`。

## 8) Whole-Word 辅助模式
保留并继续输出：
- `family_safe_whole_word`
- `free_decode_level_all`

用途：
- baseline 对照
- 观察同层混淆
- 为 posterior / phone-level 证据提供辅助 decode 结果

说明：这两者均非正式默认评分主路径。

## 9) 本次重跑结果（2026-03-30）
### 9.1 Whole-word 对照（`t04_diag_summary.json`）
- `single`: top1=`1.000`, top2=`1.000`
- `item_plus_confusion_family_safe`: top1=`0.083`, top2=`0.500`
- `level_all`: top1=`0.083`, top2=`0.306`

结论：大闭集 Top1 不适合作为 T04_EN 正式诊断主分数，保留为辅助分析。

### 9.2 Micro-probe（`t04_micro_probe_summary.json`，`margin=0.0`, `small_margin=0.05`, `duration=1.2`）
- `onset_probe`：
  - accept rate=`0.194`
  - reject rate=`0.611`
  - uncertain rate=`0.194`
  - error trigger rate=`0.611`
  - duration fallback trigger rate=`0.000`
  - raw margin 分布：min=`-1.049`，p50=`-0.052`，max=`0.525`
- `vowel_probe`：
  - accept rate=`0.000`
  - reject rate=`0.000`
  - uncertain rate=`1.000`
  - error trigger rate=`0.000`
  - duration fallback trigger rate=`1.000`
  - raw margin 分布全 `0.0`
  - duration evidence 分布：ratio 全 `1.0`
- `pattern_probe`：
  - accept rate=`0.000`
  - reject rate=`0.000`
  - uncertain rate=`1.000`
  - error trigger rate=`0.000`
  - duration fallback trigger rate=`1.000`
  - raw margin 分布全 `0.0`
  - duration evidence 分布：ratio 全 `1.0`

结论：
- onset 维度已可用 raw margin 形成 accept/reject/uncertain 三分。
- vowel/pattern 当前触发了 duration fallback，但 span 时长比仍为 1.0，故保持 uncertain。
- `raw_margin=0` 不能直接解释为“同一路径”；必须先经过 probe 体检确认。

## 10) 正式口径更新
1. T04_EN 不再把 whole-word Top1 作为唯一正式评分依据。
2. `micro-probe scoring` 是当前推荐正式诊断路径。
3. 不推荐 `global normalized_score_per_frame` 作为 T04 micro-probe 主判据。
4. 推荐 `probe-local raw cost delta / log-like margin`。
5. `lattice-to-post` 不是直接词 posterior 工具。
6. phone-level evidence 通过 `lattice-align-phones / lattice-arc-post` 补充。
7. onset 已可用 raw margin 诊断。
8. vowel/pattern 需要 local span + duration 证据。
9. duration-based fallback 是二级证据，不是无条件覆盖规则。
10. 自由解码/level_all 保留为辅助分析模式。

## 11) 关键命令
```bash
cd /home/yoeseka/kaldi

./egs/t04_en_constrained/s5/scripts/build_t04_grammars.sh \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime

./egs/t04_en_constrained/s5/scripts/build_t04_graphs.sh \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime

./egs/t04_en_constrained/s5/scripts/inspect_t04_graphs.sh \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime

python3 egs/t04_en_constrained/s5/scripts/run_t04_diagnostic_experiment.py \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime \
  --wav-dir /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/wavs_espeak_ipa_16k

python3 egs/t04_en_constrained/s5/scripts/check_t04_probe_health.py \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime \
  --wav-dir /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/wavs_espeak_ipa_16k

python3 egs/t04_en_constrained/s5/scripts/score_t04_micro_probes.py \
  --runtime-root /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime \
  --wav-dir /home/yoeseka/kaldi/egs/t04_en_constrained/s5/runtime/diagnostic/wavs_espeak_ipa_16k \
  --small-margin-threshold 0.05 \
  --duration-threshold 1.2
```
