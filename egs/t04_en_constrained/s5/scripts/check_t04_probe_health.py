#!/usr/bin/env python3

import argparse
import json
import shlex
import subprocess
import tempfile
from pathlib import Path


CASES = [
    {
        "name": "fot_vs_fote",
        "probe_type": "vowel_probe",
        "target": "fot",
        "competitor": "fote",
        "graph_name": "T04_PROBE_T04_CVC_fot_VOWEL",
        "wav_name": "cvc_fot_r1.wav",
    },
    {
        "name": "gop_vs_gope",
        "probe_type": "vowel_probe",
        "target": "gop",
        "competitor": "gope",
        "graph_name": "T04_PROBE_T04_CVC_gop_VOWEL",
        "wav_name": "cvc_gop_r1.wav",
    },
    {
        "name": "fotting_vs_foting",
        "probe_type": "pattern_probe",
        "target": "fotting",
        "competitor": "foting",
        "graph_name": "T04_PROBE_T04_ING_B_fotting_PATTERN",
        "wav_name": "ing_b_fotting_r1.wav",
    },
    {
        "name": "gopping_vs_goping",
        "probe_type": "pattern_probe",
        "target": "gopping",
        "competitor": "goping",
        "graph_name": "T04_PROBE_T04_ING_B_gopping_PATTERN",
        "wav_name": "ing_b_gopping_r1.wav",
    },
]


def run_sh(cmd: str) -> tuple[bool, str]:
    p = subprocess.run(["bash", "-lc", cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode == 0:
        return True, ""
    tail = (p.stderr or "").strip().splitlines()
    return False, tail[-1] if tail else "unknown_error"


def load_align_lexicon(path: Path) -> dict[str, list[str]]:
    m = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 3:
            m[cols[1]] = cols[2:]
    return m


def load_sym(path: Path) -> dict[str, str]:
    m = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            m[cols[1]] = cols[0]
    return m


def parse_key_map(path: Path) -> dict[str, list[str]]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            out[cols[0]] = cols[1:]
    return out


def parse_float_map(path: Path) -> dict[str, float]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            try:
                out[cols[0]] = float(cols[1])
            except Exception:
                pass
    return out


def span_for_probe(phone_seq: list[str], probe_type: str) -> tuple[int | None, int | None, int]:
    if probe_type == "vowel_probe":
        targets = {"O_SHORT_I", "O_LONG_I"}
        idx = next((i for i, p in enumerate(phone_seq) if p in targets), None)
        if idx is None:
            return None, None, 0
        j = idx
        while j + 1 < len(phone_seq) and phone_seq[j + 1] == phone_seq[idx]:
            j += 1
        return idx, j, j - idx + 1

    ih_idx = next((i for i, p in enumerate(phone_seq) if p.startswith("IH_")), None)
    if ih_idx is None:
        return None, None, 0
    c_idx = None
    for i in range(max(0, ih_idx - 3), ih_idx):
        if phone_seq[i].startswith("T_") or phone_seq[i].startswith("P_"):
            c_idx = i
    if c_idx is None:
        return None, None, 0
    return c_idx, c_idx, 1


def inspect_one_case(
    case: dict,
    s5_root: Path,
    runtime_root: Path,
    model_dir: Path,
    wav_dir: Path,
    lexicon: dict[str, list[str]],
    global_word_sym: dict[str, str],
    phones_sym: dict[str, str],
    acoustic_scale: float,
) -> dict:
    graph_dir = runtime_root / "graphs" / case["graph_name"]
    lang_graph = runtime_root / "lang_graphs" / case["graph_name"]
    words_txt = lang_graph / "words.txt"
    wav = wav_dir / case["wav_name"]

    target = case["target"]
    competitor = case["competitor"]
    lex_t = lexicon.get(target, [])
    lex_c = lexicon.get(competitor, [])
    lex_diff = lex_t != lex_c

    # graph branching check
    graph_words = set()
    if graph_dir.joinpath("HCLG.fst").exists():
        cmd = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            f"fstprint --osymbols={shlex.quote(str(words_txt))} {shlex.quote(str(graph_dir / 'HCLG.fst'))}"
        )
        ok, _ = run_sh(cmd)
        if ok:
            out = subprocess.check_output(["bash", "-lc", cmd], text=True)
            for line in out.splitlines():
                cols = line.strip().split()
                if len(cols) >= 4:
                    tok = cols[3]
                    if tok not in {"<eps>", "!SIL"}:
                        graph_words.add(tok)
    graph_has_both = target in graph_words and competitor in graph_words

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        spk2utt = td / "spk2utt"
        wav_scp = td / "wav.scp"
        lat = td / "lat.1.gz"
        ali = td / "nbest_ali.txt"
        nbest_words = td / "nbest_words.txt"
        nbest_lm = td / "nbest_lm.txt"
        nbest_ac = td / "nbest_ac.txt"
        ali_phones = td / "ali_phones.txt"

        spk2utt.write_text("utt1 utt1\n", encoding="utf-8")
        wav_scp.write_text(f"utt1 {wav}\n", encoding="utf-8")

        decode_cmd = [
            "online2-wav-nnet3-latgen-faster",
            "--online=false",
            "--do-endpointing=false",
            f"--config={model_dir / 'conf' / 'online.conf'}",
            f"--mfcc-config={model_dir / 'conf' / 'mfcc.conf'}",
            f"--ivector-extraction-config={model_dir / 'conf' / 'ivector_extractor.conf'}",
            f"--word-symbol-table={words_txt}",
            "--beam=15.0",
            "--lattice-beam=8.0",
            f"--acoustic-scale={acoustic_scale}",
            str(model_dir / "final.mdl"),
            str(graph_dir / "HCLG.fst"),
            f"ark:{spk2utt}",
            f"scp:{wav_scp}",
            f"ark:|gzip -c >{lat}",
        ]
        decode_sh = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            + " ".join(shlex.quote(x) for x in decode_cmd)
        )
        ok_decode, err_decode = run_sh(decode_sh)
        if not ok_decode:
            return {
                "case": case,
                "lexicon_target_phones": lex_t,
                "lexicon_competitor_phones": lex_c,
                "lexicon_phones_different": lex_diff,
                "graph_has_target_competitor_branching": graph_has_both,
                "decode_ok": False,
                "decode_error": err_decode,
                "likely_root_cause": "scoring_extraction_implementation_issue",
            }

        nbest_sh = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            f"lattice-to-nbest --n=8 'ark:gunzip -c {lat}|' ark:- "
            f"| nbest-to-linear ark:- ark,t:{ali} ark,t:{nbest_words} ark,t:{nbest_lm} ark,t:{nbest_ac}"
        )
        run_sh(nbest_sh)

        ali_phone_sh = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            f"ali-to-phones --per-frame=true {shlex.quote(str(model_dir / 'final.mdl'))} "
            f"ark,t:{ali} ark,t:{ali_phones}"
        )
        run_sh(ali_phone_sh)

        words_map = parse_key_map(nbest_words)
        lm_map = parse_float_map(nbest_lm)
        ac_map = parse_float_map(nbest_ac)
        phone_map = parse_key_map(ali_phones)

        # candidate record by word symbol
        cand = {}
        for key, toks in words_map.items():
            if not toks:
                continue
            word = global_word_sym.get(toks[0], toks[0])
            phones = [phones_sym.get(pid, pid) for pid in phone_map.get(key, [])]
            total = None
            if key in lm_map and key in ac_map:
                total = lm_map[key] + ac_map[key]
            s0, s1, span_len = span_for_probe(phones, case["probe_type"])
            cand[word] = {
                "nbest_key": key,
                "lm_cost": lm_map.get(key),
                "ac_cost": ac_map.get(key),
                "total_cost": total,
                "phones_per_frame": phones,
                "diagnostic_span_start": s0,
                "diagnostic_span_end": s1,
                "diagnostic_span_frames": span_len,
            }

        t = cand.get(target)
        c = cand.get(competitor)

        score_independent = bool(t and c and t.get("total_cost") is not None and c.get("total_cost") is not None)
        raw_margin = None
        if score_independent:
            raw_margin = c["total_cost"] - t["total_cost"]

        align_diff = bool(t and c and t["phones_per_frame"] != c["phones_per_frame"])
        span_observable = bool(t and c and t["diagnostic_span_frames"] > 0 and c["diagnostic_span_frames"] > 0)

        if not lex_diff or not graph_has_both:
            cause = "lexicon_or_graph_not_distinguishing_target_competitor"
        elif not score_independent:
            cause = "scoring_extraction_implementation_issue"
        elif raw_margin == 0.0 and align_diff:
            cause = "local_difference_exists_but_global_or_current_scoring_is_insensitive"
        elif raw_margin == 0.0 and not align_diff:
            cause = "likely_same_path_or_missing_local_distinction"
        else:
            cause = "scoring_is_distinguishing_hypotheses"

        return {
            "case": case,
            "lexicon_target_phones": lex_t,
            "lexicon_competitor_phones": lex_c,
            "lexicon_phones_different": lex_diff,
            "graph_has_target_competitor_branching": graph_has_both,
            "decode_ok": True,
            "target_record": t,
            "competitor_record": c,
            "alignment_phone_or_span_difference_observed": align_diff,
            "diagnostic_span_observable": span_observable,
            "score_extraction_compares_independent_hypotheses": score_independent,
            "raw_margin_competitor_minus_target": raw_margin,
            "likely_root_cause": cause,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="T04 micro-probe health check for zero-margin diagnostics.")
    ap.add_argument("--runtime-root", default="egs/t04_en_constrained/s5/runtime")
    ap.add_argument("--wav-dir", default="egs/t04_en_constrained/s5/runtime/diagnostic/wavs_espeak_ipa_16k")
    ap.add_argument("--model-dir", default="")
    ap.add_argument("--acoustic-scale", type=float, default=0.1)
    ap.add_argument("--output-json", default="")
    ap.add_argument("--output-md", default="")
    args = ap.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    s5_root = runtime_root.parent
    wav_dir = Path(args.wav_dir).resolve()
    model_dir = Path(args.model_dir).resolve() if args.model_dir else (runtime_root / "model" / "m13_librispeech_resolved")

    out_root = runtime_root / "diagnostic"
    output_json = Path(args.output_json).resolve() if args.output_json else out_root / "t04_probe_health_report.json"
    output_md = Path(args.output_md).resolve() if args.output_md else out_root / "t04_probe_health_report.md"

    lex = load_align_lexicon(runtime_root / "lang" / "lang_t04" / "phones" / "align_lexicon.txt")
    global_words = load_sym(runtime_root / "lang" / "lang_t04" / "words.txt")
    phones_sym = load_sym(runtime_root / "lang" / "lang_t04" / "phones.txt")

    results = []
    for case in CASES:
        results.append(
            inspect_one_case(
                case=case,
                s5_root=s5_root,
                runtime_root=runtime_root,
                model_dir=model_dir,
                wav_dir=wav_dir,
                lexicon=lex,
                global_word_sym=global_words,
                phones_sym=phones_sym,
                acoustic_scale=args.acoustic_scale,
            )
        )

    # global conclusion
    causes = {}
    for r in results:
        c = r.get("likely_root_cause", "unknown")
        causes[c] = causes.get(c, 0) + 1

    report = {
        "task_id": "T04_EN",
        "cases": results,
        "cause_counts": causes,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    lines = []
    lines.append("# T04 Micro-Probe 体检报告")
    lines.append("")
    lines.append("## 结论摘要")
    for k, v in sorted(causes.items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    for r in results:
        c = r["case"]
        lines.append(f"## {c['name']}")
        lines.append(f"- probe: `{c['graph_name']}` ({c['probe_type']})")
        lines.append(f"- check1 lexicon phone 不同: `{r.get('lexicon_phones_different')}`")
        lines.append(f"- check2 graph 分叉存在: `{r.get('graph_has_target_competitor_branching')}`")
        lines.append(
            f"- check3 对齐中可见 phone/span 差异: `{r.get('alignment_phone_or_span_difference_observed')}`, "
            f"span_observable=`{r.get('diagnostic_span_observable')}`"
        )
        lines.append(
            f"- check4 独立假设比较: `{r.get('score_extraction_compares_independent_hypotheses')}`, "
            f"raw_margin={r.get('raw_margin_competitor_minus_target')}"
        )
        lines.append(f"- check5 最可能原因: `{r.get('likely_root_cause')}`")
        lines.append("")
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote probe health json: {output_json}")
    print(f"wrote probe health md: {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
