# T12_ZH_PINYIN 维护文档

本文档记录 `T12_ZH_PINYIN` 当前已经完成的工作、当前产物位置、以及下一步建议。
最后同步时间：`2026-03-30`。

## 当前状态

`T12_ZH_PINYIN` 已经从“任务骨架”推进到“可用 M11 模型资产生成 constrained-decode graph”的阶段。

当前已经完成：
- 独立任务目录已经建立在 [egs/t12_zh_pinyin/s5](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5)
- `surface_form / word_id / phone_sequence / onset_probe / final_probe / tone_probe` 主表已经固定在 [t12_items_master.csv](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/config/t12_items_master.csv)
- probe 注册逻辑已经固定为 `onset_probe / final_probe / tone_probe`，脚本在 [t12_generate_registry.py](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/scripts/t12_generate_registry.py)
- 官方 Kaldi Multi_CN M11 在线模型已经下载、解包并固化到 [m11_resolved](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved)
- M11 资产 manifest 已写入 [model_manifest.json](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/manifests/model_manifest.json) 和 [model_paths.env](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/manifests/model_paths.env)
- T12 词典生成器已经能把任务层拼音 phoneset 映射到 `multi_cn` 的 CMU-like phones，并按 M11 `phones.txt` 做兼容校验，脚本在 [generate_t12_dict_template.py](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/scripts/generate_t12_dict_template.py)
- display 与内部 token 已分离，映射表在 [t12_display_to_token.tsv](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/config/t12_display_to_token.tsv)
- M11-compatible 词典目录已经生成在 [dict_T12_ZH_PINYIN_m11](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/dict_T12_ZH_PINYIN_m11)
- `prepare_lang.sh --phone-symbol-table` 已经跑通，`lang_t12` 已生成在 [lang_t12](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/lang/lang_t12)
- formal graph 和全部 probe graph 已经生成在 [runtime/graphs](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/graphs)
- graph/manifest 注册已经生成在 [t12_graph_manifest.json](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/manifests/t12_graph_manifest.json) 和 [t12_probe_manifest.json](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/manifests/t12_probe_manifest.json)
- manifest 已引入稳定字段 `graph_status`（不再仅靠 `notes` 内嵌 `build_status`）
- 图资产体检脚本已补齐：[inspect_t12_graphs.sh](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/scripts/inspect_t12_graphs.sh)
- micro-probe 评分脚本已补齐：[score_t12_micro_probes.py](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/scripts/score_t12_micro_probes.py)

## 关键实现点

### 1. T12 不复用 T04 英文模型

`T12_ZH_PINYIN` 使用的是独立中文任务目录和独立中文模型路径，不依赖 `T04_EN` 的英文模型。

### 2. probe 维度已经按中文任务改写

当前 T12 只生成三类 probe：
- `onset_probe`
- `final_probe`
- `tone_probe`

没有沿用 `T04_EN` 的 `vowel_length / pattern`。

### 3. M11 phoneset 兼容路径已经打通

这一轮最关键的工作不是“把拼音直接塞进词典”，而是把 T12 任务层 phoneset 和 M11 的真实 `phones.txt` 对齐。

当前实际做法是：
- 任务层仍然保持 `dao4 / xue3 / nue3` 这类稳定 `word_id`
- 任务层 `phone_sequence` 采用无调 phones（如 `d ao`、`x ve`）
- 再通过 `egs/multi_cn/s5/conf/pinyin2cmu` 映射成 M11 对应 phone family
- `ue` 系统按 `ve` 归一（例如 `x ve / j ve / n ve / y ve`）
- `nonsilence_phones.txt` 不只包含 T12 当前用到的 phones，而是按 M11 全量 inventory 生成
- `extra_questions.txt` 除了 T12 自己的 onset/final/tone 诊断分组，还补入 model-wide tone questions，保证 `prepare_lang.sh` 不会因为同根 phone 无法区分而失败

### 4. dict 生成和 lang 构建的实际口径

当前的正确口径是：
- `dict/lexicon.txt` 里写无调 base phones，如 `dao4 D AW`
- 不在词典源文件里直接写 `_B/_I/_E/_S`
- 让 `prepare_lang.sh` 自己根据 `position_dependent_phones=true` 展开
- 再用 `--phone-symbol-table` 对齐到 M11 的官方 `phones.txt`
- `tone_probe` 继续保留在 token 维度（`dao1|dao2|dao3|dao4`），不把 tone 硬塞进任务层 phone_sequence

## 当前主要产物

### 模型资产
- [final.mdl](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved/final.mdl)
- [tree](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved/tree)
- [phones.txt](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved/phones.txt)
- [words.txt](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved/words.txt)
- [mfcc.conf](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved/conf/mfcc.conf)
- [online.conf](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved/conf/online.conf)
- [ivector_extractor](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved/ivector_extractor)

### 词典 / lang / graph
- [dict_T12_ZH_PINYIN_m11](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/dict_T12_ZH_PINYIN_m11)
- [lang_t12](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/lang/lang_t12)
- [runtime/grammar/fsts](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/grammar/fsts)
- [runtime/lang_graphs](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/lang_graphs)
- [runtime/graphs](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/graphs)

### manifest
- [t12_graph_manifest.json](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/manifests/t12_graph_manifest.json)
- [t12_probe_manifest.json](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/manifests/t12_probe_manifest.json)

## 已执行并通过的关键步骤

已实际执行：
```bash
python3 egs/t12_zh_pinyin/s5/scripts/register_t12_m11_assets.py \
  --model-dir /home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved

bash egs/t12_zh_pinyin/s5/scripts/build_t12_m11_dict.sh
bash egs/t12_zh_pinyin/s5/scripts/build_t12_lang.sh --force-rebuild
bash egs/t12_zh_pinyin/s5/scripts/build_t12_grammars.sh
bash egs/t12_zh_pinyin/s5/scripts/build_t12_graphs.sh
bash egs/t12_zh_pinyin/s5/scripts/inspect_t12_graphs.sh
```

已确认通过：
- `python3 -m py_compile` 针对新增 Python 脚本通过
- `validate_dict_dir.pl` 针对 [dict_T12_ZH_PINYIN_m11](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/dict_T12_ZH_PINYIN_m11) 通过
- `utils/prepare_lang.sh --phone-symbol-table ...` 针对 `lang_t12` 通过
- `utils/validate_lang.pl` 针对 [lang_t12](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/lang/lang_t12) 通过
- `utils/mkgraph.sh` 已为 formal graph 和 probe graphs 生成 HCLG 资产
- `inspect_t12_graphs.sh` 已校验 manifest 字段完整性、FST 与 candidate 一致性、graph/probe manifest 对齐
- `score_t12_micro_probes.py` 已基于 demo evidence 生成评分产物

## 当前还没做的事

目前还没有做：
- engine / FastAPI 的 `T12` 独立调用入口
- shadow mode 接入主项目

## 下一步建议

建议继续按这个顺序推进：

1. 增加 engine/FastAPI 独立入口。
   目标：先以 shadow mode 接入，不直接替换正式评分。

2. 明确 decode evidence 统一协议。
   目标：固定 `score_t12_micro_probes.py` 的上游输入字段，减少联调期字段漂移。

3. 补 shadow-mode 对比报表。
   目标：并行输出 T04/T12 评分差异，支持灰度观察。

## 评分脚本输入输出口径

脚本 [score_t12_micro_probes.py](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/scripts/score_t12_micro_probes.py) 当前口径：
- 输入：`--decode-evidence-json`（list 结构；每条含 `target_word`，可选 `probe_costs` / `candidate_raw_costs`）
- 输出文件：[t12_micro_probe_results.json](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/diagnostic/t12_micro_probe_results.json)
- 输出文件：[t12_micro_probe_summary.json](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/diagnostic/t12_micro_probe_summary.json)
- 输出文件：[t12_micro_probe_results.csv](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/diagnostic/t12_micro_probe_results.csv)

最小命令：
```bash
python3 egs/t12_zh_pinyin/s5/scripts/score_t12_micro_probes.py \
  --decode-evidence-json egs/t12_zh_pinyin/s5/runtime/diagnostic/t12_probe_decode_evidence.json
```

## 文档维护清单

每次改动以下任一项时，同步更新本文档和 [README.md](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/README.md)：
- 脚本入口新增/删除（`scripts/`）
- manifest 字段变更（`runtime/manifests/*.json`）
- 评分输入输出协议变化（decode evidence 字段、summary 字段）
- 正式推进节点变化（例如从 skeleton 到 shadow-mode）

## 维护注意事项

- 不要把 T12 逻辑混进 `t04_*` 文件。
- 更新 M11 模型资产时，只改 [m11_resolved](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/runtime/model/m11_resolved) 和对应 manifest，不要手改 T12 词典中的 `word_id`。
- 新增 formal item 或 probe candidate 时，优先改 [t12_items_master.csv](/home/yoeseka/kaldi/egs/t12_zh_pinyin/s5/config/t12_items_master.csv)，然后按顺序重跑 `build_t12_m11_dict.sh`、`build_t12_lang.sh`、`build_t12_grammars.sh`、`build_t12_graphs.sh`、`inspect_t12_graphs.sh`。
