# Kaldi+WFST 新题扩展指南

本指南用于后续从 `T04_EN` 扩展到其他题目（同技术栈：Kaldi + WFST）。

## 1. 推荐做法
1. 复制骨架目录：`egs/t04_en_constrained/s5` 到新题目录（例如 `egs/t05_xx_constrained/s5`）。
2. 全量重命名 `t04` 前缀为新题前缀，避免混淆。
3. 仅复用脚本框架，不复用 T04 词集/confusion 具体内容。

## 2. 最小落地清单
- 配置：
  - `config/<task>_word_sets.json`
  - `config/<task>_confusion_sets.json`
- 构建：
  - `scripts/build_<task>_lang.sh`
  - `scripts/build_<task>_grammars.sh`
  - `scripts/build_<task>_graphs.sh`
  - `scripts/inspect_<task>_graphs.sh`
- 诊断：
  - `scripts/check_<task>_probe_health.py`
  - `scripts/score_<task>_micro_probes.py`
- 产物：
  - `runtime/manifests/<task>_graph_manifest.json`
  - `runtime/manifests/<task>_probe_manifest.json`
  - `runtime/diagnostic/<task>_*`

## 3. 评分策略建议
- 正式主路径：micro-probe candidate-specific scoring
- 主判据：probe-local raw margin（同音频、同 probe、同 acoustic scale）
- 次级证据：local phone span + duration fallback
- whole-word（level_all/family_safe）仅辅助，不作正式默认评分

## 4. 必做验证顺序
1. 先做 `probe health check`（词典、图分叉、独立假设比较、raw_margin 归因）。
2. 再跑 micro-probe 正式诊断。
3. 最后再看 whole-word 辅助对照。

## 5. 文档要求
每个新题必须有独立设计文档，至少写清：
1. 正式默认评分口径
2. raw margin 比较范围约束
3. duration fallback 触发条件
4. phone-level evidence 的来源与边界
