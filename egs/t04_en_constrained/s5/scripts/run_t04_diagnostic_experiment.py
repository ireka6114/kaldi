#!/usr/bin/env python3

import argparse
import csv
import json
import math
import shlex
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


MODE_TO_SUFFIX = {
    "single": "SINGLE",
    "item_plus_confusion_family_safe": "FAMILY_SAFE",
    "level_all": "LEVEL_ALL",
}

LEVEL_PLAN = [
    ("T04_CVC", 2),
    ("T04_CVCE", 2),
    ("T04_ING_A", 1),
    ("T04_ING_B", 1),
]


@dataclass
class DecodeOutput:
    best_candidate: str | None
    top_candidates: list[str]
    top_costs: list[float]
    confidence: float | None
    phone_alignment_available: bool
    notes: list[str]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_model_dir(runtime_root: Path, explicit_model_dir: str | None) -> Path:
    if explicit_model_dir:
        return Path(explicit_model_dir).resolve()

    env_file = runtime_root / "manifests" / "model_paths.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("T04_MODEL_DIR="):
                return Path(line.split("=", 1)[1]).resolve()

    return (runtime_root / "model").resolve()


def read_word_id_map(words_txt: Path) -> dict[str, str]:
    m = {}
    for line in words_txt.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            m[parts[1]] = parts[0]
    return m


def safe_float(token: str) -> float | None:
    try:
        return float(token)
    except Exception:
        return None


def parse_nbest_words(
    words_path: Path,
    weights_path: Path,
    word_id_map: dict[str, str],
    max_n: int = 3,
) -> tuple[list[str], list[float]]:
    candidates: list[str] = []
    costs: list[float] = []

    words_lines = words_path.read_text(encoding="utf-8").splitlines() if words_path.exists() else []
    weight_lines = weights_path.read_text(encoding="utf-8").splitlines() if weights_path.exists() else []

    key_to_cost: dict[str, float] = {}
    for line in weight_lines:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        c = safe_float(parts[1])
        if c is not None:
            key_to_cost[parts[0]] = c

    for line in words_lines:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        key = parts[0]
        words = [word_id_map.get(tok, tok) for tok in parts[1:]]
        cand = " ".join(words).strip()
        if not cand:
            continue
        candidates.append(cand)
        costs.append(key_to_cost.get(key, math.nan))

    uniq_candidates = []
    uniq_costs = []
    seen = set()
    for cand, c in zip(candidates, costs):
        if cand in seen:
            continue
        seen.add(cand)
        uniq_candidates.append(cand)
        uniq_costs.append(c)
        if len(uniq_candidates) >= max_n:
            break
    return uniq_candidates, uniq_costs


def score_confidence(costs: list[float]) -> float | None:
    if not costs:
        return None
    if len(costs) == 1 or math.isnan(costs[0]):
        return 1.0
    c1 = costs[0]
    c2 = costs[1] if len(costs) > 1 else math.nan
    if math.isnan(c2):
        return 1.0
    x1 = math.exp(-c1)
    x2 = math.exp(-c2)
    denom = x1 + x2
    if denom <= 0.0:
        return None
    return x1 / denom


def top_posterior_summary(cands: list[str], costs: list[float]) -> list[dict]:
    usable = [(c, s) for c, s in zip(cands, costs) if not math.isnan(s)]
    if not usable:
        return [{"candidate": c, "posterior": None, "cost": None if math.isnan(s) else s} for c, s in zip(cands, costs)]

    vals = [math.exp(-s) for _, s in usable]
    denom = sum(vals)
    post = {}
    if denom > 0.0:
        for (cand, _), v in zip(usable, vals):
            post[cand] = v / denom

    out = []
    for cand, cost in zip(cands, costs):
        out.append(
            {
                "candidate": cand,
                "posterior": post.get(cand),
                "cost": None if math.isnan(cost) else cost,
            }
        )
    return out


def run_kaldi_cmd(sh_cmd: str) -> tuple[bool, str]:
    proc = subprocess.run(["bash", "-lc", sh_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ok = proc.returncode == 0
    tail = (proc.stderr or "").strip().splitlines()
    tail_msg = tail[-1] if tail else ""
    return ok, tail_msg


def run_decode(
    wav_path: Path,
    graph_dir: Path,
    words_txt: Path,
    model_dir: Path,
    s5_root: Path,
) -> DecodeOutput:
    notes = []

    final_mdl = model_dir / "final.mdl"
    online_conf = model_dir / "conf" / "online.conf"
    mfcc_conf = model_dir / "conf" / "mfcc.conf"
    iv_conf = model_dir / "conf" / "ivector_extractor.conf"
    word_boundary = graph_dir / "phones" / "word_boundary.int"

    for p, tag in [
        (wav_path, "missing_wav"),
        (graph_dir / "HCLG.fst", "missing_hclg"),
        (words_txt, "missing_words_txt"),
        (final_mdl, "missing_final_mdl"),
        (online_conf, "missing_online_conf"),
        (mfcc_conf, "missing_mfcc_conf"),
        (iv_conf, "missing_ivector_extractor_conf"),
        (model_dir / "ivector_extractor", "missing_ivector_extractor"),
    ]:
        if not p.exists():
            notes.append(tag)

    if notes:
        return DecodeOutput(
            best_candidate=None,
            top_candidates=[],
            top_costs=[],
            confidence=None,
            phone_alignment_available=False,
            notes=notes,
        )

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        spk2utt = tdir / "spk2utt"
        wav_scp = tdir / "wav.scp"
        lat_gz = tdir / "lat.1.gz"
        aligned_lat_gz = tdir / "lat.phone_aligned.1.gz"
        best_txt = tdir / "best.txt"
        ali_txt = tdir / "ali.txt"
        nbest_words_txt = tdir / "nbest_words.txt"
        nbest_weights_txt = tdir / "nbest_weights.txt"
        ctm_conf = tdir / "ctm.conf"

        spk2utt.write_text("utt1 utt1\n", encoding="utf-8")
        wav_scp.write_text(f"utt1 {wav_path}\n", encoding="utf-8")

        decode_cmd = [
            "online2-wav-nnet3-latgen-faster",
            "--online=false",
            "--do-endpointing=false",
            f"--config={online_conf}",
            f"--mfcc-config={mfcc_conf}",
            f"--ivector-extraction-config={iv_conf}",
            f"--word-symbol-table={words_txt}",
            "--beam=15.0",
            "--lattice-beam=8.0",
            "--acoustic-scale=0.1",
            str(final_mdl),
            str(graph_dir / "HCLG.fst"),
            f"ark:{spk2utt}",
            f"scp:{wav_scp}",
            f"ark:|gzip -c >{lat_gz}",
        ]
        decode_sh = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            + " ".join(shlex.quote(x) for x in decode_cmd)
        )
        ok, _ = run_kaldi_cmd(decode_sh)
        if not ok:
            notes.append("decode_failed")
            return DecodeOutput(
                best_candidate=None,
                top_candidates=[],
                top_costs=[],
                confidence=None,
                phone_alignment_available=False,
                notes=notes,
            )

        best_cmd = [
            "lattice-best-path",
            f"--word-symbol-table={words_txt}",
            f"ark:gunzip -c {lat_gz}|",
            f"ark,t:{best_txt}",
        ]
        best_sh = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            + " ".join(shlex.quote(x) for x in best_cmd)
        )
        run_kaldi_cmd(best_sh)

        nbest_cmd = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            f"lattice-to-nbest --n=3 'ark:gunzip -c {lat_gz}|' ark:- "
            f"| nbest-to-linear ark:- ark,t:{ali_txt} ark,t:{nbest_words_txt} ark,t:{nbest_weights_txt}"
        )
        run_kaldi_cmd(nbest_cmd)

        word_id_map = read_word_id_map(words_txt)
        top_candidates, costs = parse_nbest_words(nbest_words_txt, nbest_weights_txt, word_id_map, max_n=3)

        best_candidate = None
        if best_txt.exists():
            line = best_txt.read_text(encoding="utf-8").strip().splitlines()
            if line:
                parts = line[0].strip().split()
                ids = parts[1:]
                mapped = [word_id_map.get(tok, tok) for tok in ids]
                if mapped:
                    best_candidate = " ".join(mapped)

        if best_candidate and (not top_candidates or top_candidates[0] != best_candidate):
            merged = [best_candidate] + [x for x in top_candidates if x != best_candidate]
            top_candidates = merged[:3]

        conf = score_confidence(costs)

        phone_alignment_available = False
        if word_boundary.exists():
            align_sh = (
                f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
                f"lattice-align-phones {shlex.quote(str(final_mdl))} "
                f"'ark:gunzip -c {lat_gz}|' 'ark:|gzip -c >{aligned_lat_gz}'"
            )
            align_ok, _ = run_kaldi_cmd(align_sh)
            if align_ok and aligned_lat_gz.exists():
                phone_alignment_available = True
                notes.append("lattice_align_phones_ok")
                ctm_src = aligned_lat_gz
            else:
                notes.append("lattice_align_phones_failed")
                ctm_src = lat_gz

            ctm_sh = (
                f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
                f"lattice-to-ctm-conf --acoustic-scale=0.1 --word-boundary={shlex.quote(str(word_boundary))} "
                f"'ark:gunzip -c {ctm_src}|' {shlex.quote(str(ctm_conf))}"
            )
            ctm_ok, _ = run_kaldi_cmd(ctm_sh)
            notes.append("lattice_to_ctm_conf_ok" if ctm_ok else "lattice_to_ctm_conf_failed")
        else:
            notes.append("missing_word_boundary_for_ctm")

        notes.append("decode_success")
        return DecodeOutput(
            best_candidate=best_candidate,
            top_candidates=top_candidates,
            top_costs=costs,
            confidence=conf,
            phone_alignment_available=phone_alignment_available,
            notes=notes,
        )


def build_eval_rows(config_json: Path) -> list[dict[str, str]]:
    conf = read_json(config_json)
    formal = conf["formal_levels"]
    rows = []
    for level_key, rep_count in LEVEL_PLAN:
        info = formal[level_key]
        level = info["level_tag"]
        source_set = info["source_set"]
        for word in info["words"]:
            for rep in range(1, rep_count + 1):
                utt_id = f"{source_set.lower()}_{word}_r{rep}"
                rows.append(
                    {
                        "utt_id": utt_id,
                        "target_word": word,
                        "level": level,
                        "source_set": source_set,
                        "rep": str(rep),
                        "parent_level_graph": level_key,
                    }
                )
    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def infer_bottleneck(results: list[dict]) -> str:
    by_mode = defaultdict(list)
    for r in results:
        by_mode[r["mode"]].append(1 if r["is_correct"] else 0)

    def acc(mode: str) -> float:
        xs = by_mode.get(mode, [])
        return (sum(xs) / len(xs)) if xs else 0.0

    a_single = acc("single")
    a_family = acc("item_plus_confusion_family_safe")
    a_all = acc("level_all")

    if (a_single - a_all) >= 0.25 and a_single >= 0.7:
        if (a_single - a_family) <= 0.15:
            return (
                "主要瓶颈更偏向 graph/candidate 约束设计：level_all 放宽后混淆显著上升；"
                "family-safe 模式已明显缓解并接近 single。"
            )
        return (
            "主要瓶颈更偏向 graph/candidate 约束设计：single 明显高于 level_all，"
            "放宽候选集合后混淆快速上升。"
        )

    if a_single < 0.55 and abs(a_single - a_all) < 0.12:
        return (
            "主要瓶颈更偏向 acoustic mismatch：即便 single 约束下准确率也偏低，"
            "且多种 mode 差距不大。"
        )

    return (
        "瓶颈呈混合态：存在 graph 约束放宽带来的混淆增加，同时 single 模式准确率"
        "仍未达到理想水平。"
    )


def summarize(results: list[dict]) -> dict:
    def ratio(rows: list[dict], key: str) -> float:
        if not rows:
            return 0.0
        return sum(1 for r in rows if r[key]) / len(rows)

    mode_groups = defaultdict(list)
    level_groups = defaultdict(list)
    family_groups = defaultdict(list)
    ing_groups = defaultdict(list)
    confusion = Counter()

    for r in results:
        mode_groups[r["mode"]].append(r)
        level_groups[(r["mode"], r["level"])].append(r)
        fam = r.get("family_name") or "none"
        family_groups[(r["mode"], fam)].append(r)
        if r["source_set"] in {"ING_A", "ING_B"}:
            ing_groups[(r["mode"], r["source_set"])].append(r)
        if r["best_candidate"] and r["best_candidate"] != r["target_word"]:
            confusion[(r["target_word"], r["best_candidate"], r["mode"])] += 1

    overall = {}
    for m, rows in mode_groups.items():
        overall[m] = {
            "n": len(rows),
            "top1_accuracy": ratio(rows, "is_correct"),
            "top2_accuracy": ratio(rows, "top2_hit"),
        }

    per_level = {}
    for (mode, level), rows in sorted(level_groups.items()):
        per_level[f"{mode}:{level}"] = {
            "n": len(rows),
            "top1_accuracy": ratio(rows, "is_correct"),
            "top2_accuracy": ratio(rows, "top2_hit"),
        }

    per_family = {}
    for (mode, family), rows in sorted(family_groups.items()):
        per_family[f"{mode}:{family}"] = {
            "n": len(rows),
            "top1_accuracy": ratio(rows, "is_correct"),
            "top2_accuracy": ratio(rows, "top2_hit"),
        }

    ing_stats = {}
    for (mode, source), rows in sorted(ing_groups.items()):
        ing_stats[f"{mode}:{source}"] = {
            "n": len(rows),
            "top1_accuracy": ratio(rows, "is_correct"),
            "top2_accuracy": ratio(rows, "top2_hit"),
        }

    confusion_pairs = [
        {
            "target_word": t,
            "best_candidate": b,
            "mode": m,
            "count": c,
        }
        for (t, b, m), c in confusion.most_common(20)
    ]

    return {
        "overall_accuracy_by_mode": overall,
        "per_level_accuracy": per_level,
        "per_family_accuracy": per_family,
        "major_confusion_pairs": confusion_pairs,
        "ing_stats": ing_stats,
        "diagnosis": infer_bottleneck(results),
    }


def write_report(path: Path, summary: dict) -> None:
    lines = []
    lines.append("# T04_EN 诊断实验报告")
    lines.append("")
    lines.append("## 总体（按 mode）")
    for mode, v in summary["overall_accuracy_by_mode"].items():
        lines.append(
            f"- {mode}: n={v['n']}, top1={v['top1_accuracy']:.3f}, top2={v['top2_accuracy']:.3f}"
        )
    lines.append("")
    lines.append("## 分 level 准确率")
    for k, v in summary["per_level_accuracy"].items():
        lines.append(f"- {k}: n={v['n']}, top1={v['top1_accuracy']:.3f}, top2={v['top2_accuracy']:.3f}")
    lines.append("")
    lines.append("## 分 family 准确率")
    for k, v in summary["per_family_accuracy"].items():
        lines.append(f"- {k}: n={v['n']}, top1={v['top1_accuracy']:.3f}, top2={v['top2_accuracy']:.3f}")
    lines.append("")
    lines.append("## 主要混淆对")
    if summary["major_confusion_pairs"]:
        for e in summary["major_confusion_pairs"][:10]:
            lines.append(f"- [{e['mode']}] {e['target_word']} -> {e['best_candidate']}: {e['count']}")
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("## ING_A / ING_B")
    for k, v in summary["ing_stats"].items():
        lines.append(f"- {k}: n={v['n']}, top1={v['top1_accuracy']:.3f}, top2={v['top2_accuracy']:.3f}")
    lines.append("")
    lines.append("## 结论")
    lines.append(summary["diagnosis"])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run 36-item T04_EN diagnostic experiment with 3 decode modes.")
    ap.add_argument("--runtime-root", default="egs/t04_en_constrained/s5/runtime")
    ap.add_argument("--config-json", default="egs/t04_en_constrained/s5/config/t04_word_sets.json")
    ap.add_argument("--manifest-path", default="")
    ap.add_argument("--model-dir", default="")
    ap.add_argument("--wav-dir", required=True)
    ap.add_argument("--eval-csv", default="")
    ap.add_argument("--results-csv", default="")
    ap.add_argument("--results-json", default="")
    ap.add_argument("--summary-json", default="")
    ap.add_argument("--report-md", default="")
    ap.add_argument("--auto-generate-tts", action="store_true")
    ap.add_argument("--tts-script", default="egs/t04_en_constrained/s5/scripts/generate_t04_tts_batch.py")
    ap.add_argument("--tts-provider", default="openai")
    ap.add_argument("--tts-model", default="gpt-4o-mini-tts")
    ap.add_argument("--tts-voice", default="alloy")
    ap.add_argument("--tts-overwrite", action="store_true")
    args = ap.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    s5_root = runtime_root.parent
    wav_dir = Path(args.wav_dir).resolve()
    config_json = Path(args.config_json).resolve()
    manifest_path = Path(args.manifest_path).resolve() if args.manifest_path else runtime_root / "manifests" / "t04_graph_manifest.json"
    model_dir = resolve_model_dir(runtime_root, args.model_dir)

    out_root = runtime_root / "diagnostic"
    eval_csv = Path(args.eval_csv).resolve() if args.eval_csv else out_root / "t04_eval_36.csv"
    results_csv = Path(args.results_csv).resolve() if args.results_csv else out_root / "t04_diag_results.csv"
    results_json = Path(args.results_json).resolve() if args.results_json else out_root / "t04_diag_results.json"
    summary_json = Path(args.summary_json).resolve() if args.summary_json else out_root / "t04_diag_summary.json"
    report_md = Path(args.report_md).resolve() if args.report_md else out_root / "t04_diag_report.md"

    eval_rows = build_eval_rows(config_json)
    write_csv(
        eval_csv,
        eval_rows,
        ["utt_id", "target_word", "level", "source_set", "rep", "parent_level_graph"],
    )
    print(f"wrote eval csv: {eval_csv} ({len(eval_rows)} rows)")

    if args.auto_generate_tts:
        wav_dir.mkdir(parents=True, exist_ok=True)
        tts_cmd = [
            "python3",
            str(Path(args.tts_script).resolve()),
            "--input-list",
            str(eval_csv),
            "--output-dir",
            str(wav_dir),
            "--text-column",
            "target_word",
            "--utt-id-column",
            "utt_id",
            "--provider",
            args.tts_provider,
            "--openai-model",
            args.tts_model,
            "--openai-voice",
            args.tts_voice,
            "--sample-rate",
            "16000",
        ]
        if args.tts_overwrite:
            tts_cmd.append("--overwrite")
        subprocess.run(tts_cmd, check=True)

    manifest = read_json(manifest_path)
    graph_entries = {e["graph_name"]: e for e in manifest["entries"]}

    modes = ["single", "item_plus_confusion_family_safe", "level_all"]
    result_rows = []

    for row in eval_rows:
        wav_path = wav_dir / f"{row['utt_id']}.wav"
        for mode in modes:
            suffix = MODE_TO_SUFFIX[mode]
            graph_name = f"T04_ITEM_{row['parent_level_graph']}_{row['target_word']}_{suffix}"
            entry = graph_entries.get(graph_name)
            if not entry:
                result_rows.append(
                    {
                        "utt_id": row["utt_id"],
                        "target_word": row["target_word"],
                        "level": row["level"],
                        "source_set": row["source_set"],
                        "mode": mode,
                        "candidate_policy": "",
                        "family_name": "",
                        "diagnostic_dimension": "",
                        "diagnostic_dimension_hint": "",
                        "is_formal_default": False,
                        "best_candidate": "",
                        "runner_up_candidate": "",
                        "competing_candidates": "",
                        "top3_candidates": "",
                        "posterior_summary": "",
                        "is_correct": False,
                        "top2_hit": False,
                        "confidence": "",
                        "short_vs_long_margin": "",
                        "vowel_duration_frames": "",
                        "onset_confusion_family": "",
                        "phone_alignment_available": False,
                        "graph_name": graph_name,
                        "candidate_set": "",
                        "notes": "missing_graph_in_manifest",
                    }
                )
                continue

            graph_dir = Path(entry["graph_dir"]).resolve()
            words_txt = Path(entry["lang_dir"]).resolve() / "words.txt"
            dec = run_decode(
                wav_path=wav_path,
                graph_dir=graph_dir,
                words_txt=words_txt,
                model_dir=model_dir,
                s5_root=s5_root,
            )

            best = dec.best_candidate or ""
            top_candidates = dec.top_candidates
            top2_hit = row["target_word"] in top_candidates[:2]
            is_correct = best == row["target_word"]
            runner_up = top_candidates[1] if len(top_candidates) > 1 else ""
            competing = [c for c in top_candidates if c != best]
            posterior = top_posterior_summary(top_candidates, dec.top_costs)
            posterior_map = {x["candidate"]: x["posterior"] for x in posterior}

            margin = ""
            if best and runner_up:
                p_best = posterior_map.get(best)
                p_run = posterior_map.get(runner_up)
                if p_best is not None and p_run is not None:
                    margin = f"{(p_best - p_run):.6f}"

            dim = entry.get("diagnostic_dimension") or ""
            short_vs_long_margin = ""
            if runner_up and ((row["target_word"].endswith("e") and not runner_up.endswith("e")) or (not row["target_word"].endswith("e") and runner_up.endswith("e"))):
                short_vs_long_margin = margin

            result_rows.append(
                {
                    "utt_id": row["utt_id"],
                    "target_word": row["target_word"],
                    "level": row["level"],
                    "source_set": row["source_set"],
                    "mode": mode,
                    "candidate_policy": entry.get("candidate_policy", ""),
                    "family_name": entry.get("family_name", "") or "",
                    "diagnostic_dimension": dim,
                    "diagnostic_dimension_hint": dim,
                    "is_formal_default": bool(entry.get("is_formal_default", False)),
                    "best_candidate": best,
                    "runner_up_candidate": runner_up,
                    "competing_candidates": "|".join(competing[:2]),
                    "top3_candidates": "|".join(top_candidates),
                    "posterior_summary": json.dumps(posterior, ensure_ascii=True),
                    "is_correct": is_correct,
                    "top2_hit": top2_hit,
                    "confidence": "" if dec.confidence is None else f"{dec.confidence:.6f}",
                    "short_vs_long_margin": short_vs_long_margin,
                    "vowel_duration_frames": "",
                    "onset_confusion_family": (entry.get("family_name", "") or "") if dim == "onset" else "",
                    "phone_alignment_available": dec.phone_alignment_available,
                    "graph_name": graph_name,
                    "candidate_set": "|".join(entry.get("candidate_words", [])),
                    "notes": "|".join(dec.notes),
                }
            )

    csv_fields = [
        "utt_id",
        "target_word",
        "level",
        "source_set",
        "mode",
        "candidate_policy",
        "family_name",
        "diagnostic_dimension",
        "diagnostic_dimension_hint",
        "is_formal_default",
        "best_candidate",
        "runner_up_candidate",
        "competing_candidates",
        "top3_candidates",
        "posterior_summary",
        "is_correct",
        "top2_hit",
        "confidence",
        "short_vs_long_margin",
        "vowel_duration_frames",
        "onset_confusion_family",
        "phone_alignment_available",
        "graph_name",
        "candidate_set",
        "notes",
    ]
    write_csv(results_csv, result_rows, csv_fields)

    summary = summarize(result_rows)

    results_json.parent.mkdir(parents=True, exist_ok=True)
    results_json.write_text(json.dumps({"rows": result_rows}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    write_report(report_md, summary)

    print(f"wrote results csv: {results_csv}")
    print(f"wrote results json: {results_json}")
    print(f"wrote summary json: {summary_json}")
    print(f"wrote report: {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
