#!/usr/bin/env python3

import argparse
import csv
import json
import subprocess
from collections import Counter
from pathlib import Path


DEFAULT_FIXED_PAIRS = "gop:gope,vop:vope,wot:wote,jop:jope"
DEFAULT_CONTROL_PAIRS = "fot:fote,zot:zote,jope:jop"


def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")


def parse_pairs(spec: str) -> list[tuple[str, str]]:
    out = []
    for part in (spec or "").split(","):
        s = part.strip()
        if not s:
            continue
        if ":" in s:
            a, b = s.split(":", 1)
        elif "/" in s:
            a, b = s.split("/", 1)
        else:
            continue
        a = a.strip()
        b = b.strip()
        if a and b and a != b:
            out.append((a, b))
    return out


def as_float(v: str) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def build_word_sets_json(path: Path, pairs: list[tuple[str, str]]) -> None:
    words = {w for p in pairs for w in p}
    cvc = sorted([w for w in words if not w.endswith("e")])
    cvce = sorted([w for w in words if w.endswith("e")])
    obj = {
        "formal_levels": {
            "T04_CVC": {"level_tag": "T04_CVC", "source_set": "CVC", "words": cvc},
            "T04_CVCE": {"level_tag": "T04_CVCE", "source_set": "CVCE", "words": cvce},
            "T04_ING_A": {"level_tag": "T04_ING_A", "source_set": "ING_A", "words": []},
            "T04_ING_B": {"level_tag": "T04_ING_B", "source_set": "ING_B", "words": []},
        }
    }
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def load_rows(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def summarize_model(rows: list[dict], ordered_pairs: list[tuple[str, str]]) -> dict:
    out = {}
    for a, b in ordered_pairs:
        sub = [
            r
            for r in rows
            if (r.get("probe_type") or "") == "vowel_probe"
            and (r.get("target_word") or "") == a
            and (r.get("best_competitor_candidate") or "") == b
        ]
        ok_rows = [r for r in sub if (r.get("phone_level_evidence_status") or "") == "ok"]
        margins = [as_float(r.get("vowel_local_margin_phone_level", "")) for r in ok_rows]
        margins = [m for m in margins if m is not None]
        zero_count = sum(1 for m in margins if m == 0.0)
        out[f"{a}/{b}"] = {
            "rows": len(sub),
            "status_ok_count": len(ok_rows),
            "status_ok_rate": (len(ok_rows) / len(sub)) if sub else 0.0,
            "phone_level_evidence_status_counts": dict(Counter(r.get("phone_level_evidence_status", "") for r in sub)),
            "decision_counts": {
                "accept": sum(1 for r in sub if (r.get("decision") or "") == "accept"),
                "reject": sum(1 for r in sub if (r.get("decision") or "") == "reject"),
                "uncertain": sum(1 for r in sub if (r.get("decision") or "") == "uncertain"),
            },
            "decision_detail_counts": dict(Counter(r.get("decision_detail", "") for r in sub)),
            "vowel_local_margin_phone_level_distribution": {
                "n": len(margins),
                "values": margins,
                "mean": (sum(margins) / len(margins)) if margins else None,
                "min": min(margins) if margins else None,
                "max": max(margins) if margins else None,
            },
            "zero_margin_pct_among_ok": (zero_count / len(margins) * 100.0) if margins else None,
        }
    return out


def compare(baseline: dict, adapted: dict) -> dict:
    out = {}
    for pair in baseline:
        b = baseline[pair]
        a = adapted.get(pair, {})
        bz = b.get("zero_margin_pct_among_ok")
        az = a.get("zero_margin_pct_among_ok")
        out[pair] = {
            "baseline_zero_margin_pct_among_ok": bz,
            "adapted_zero_margin_pct_among_ok": az,
            "delta_zero_margin_pct": (None if (bz is None or az is None) else (az - bz)),
            "baseline_status_ok_rate": b.get("status_ok_rate"),
            "adapted_status_ok_rate": a.get("status_ok_rate"),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate baseline vs adapted AM on T04 minimal vowel pairs.")
    ap.add_argument("--runtime-root", default="egs/t04_en_constrained/s5/runtime")
    ap.add_argument("--wav-dir", default="egs/t04_en_constrained/s5/runtime/diagnostic/wavs_ref_renamed_16k")
    ap.add_argument("--baseline-model-dir", required=True)
    ap.add_argument("--adapted-model-dir", required=True)
    ap.add_argument("--experiment-dir", required=True)
    ap.add_argument("--fixed-pairs", default=DEFAULT_FIXED_PAIRS)
    ap.add_argument("--control-pairs", default=DEFAULT_CONTROL_PAIRS)
    ap.add_argument("--known-am-indistinguishable-pairs", default=DEFAULT_FIXED_PAIRS)
    ap.add_argument("--acoustic-scale", type=float, default=0.1)
    ap.add_argument("--margin-threshold", type=float, default=0.0)
    ap.add_argument("--small-margin-threshold", type=float, default=0.05)
    ap.add_argument("--duration-threshold", type=float, default=1.2)
    ap.add_argument("--vowel-local-margin-threshold", type=float, default=0.05)
    args = ap.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    wav_dir = Path(args.wav_dir).resolve()
    exp_dir = Path(args.experiment_dir).resolve()
    exp_dir.mkdir(parents=True, exist_ok=True)

    fixed = parse_pairs(args.fixed_pairs)
    control = parse_pairs(args.control_pairs)
    ordered_pairs = fixed + control

    word_sets_json = exp_dir / "eval_word_sets.json"
    build_word_sets_json(word_sets_json, ordered_pairs)

    base_csv = exp_dir / "baseline_micro_probe_results.csv"
    base_json = exp_dir / "baseline_micro_probe_results.json"
    base_summary = exp_dir / "baseline_micro_probe_summary.json"

    adap_csv = exp_dir / "adapted_micro_probe_results.csv"
    adap_json = exp_dir / "adapted_micro_probe_results.json"
    adap_summary = exp_dir / "adapted_micro_probe_summary.json"

    score_script = Path("egs/t04_en_constrained/s5/scripts/score_t04_micro_probes.py").resolve()

    common = [
        "--runtime-root",
        str(runtime_root),
        "--config-json",
        str(word_sets_json),
        "--wav-dir",
        str(wav_dir),
        "--acoustic-scale",
        str(args.acoustic_scale),
        "--margin-threshold",
        str(args.margin_threshold),
        "--small-margin-threshold",
        str(args.small_margin_threshold),
        "--duration-threshold",
        str(args.duration_threshold),
        "--vowel-local-margin-threshold",
        str(args.vowel_local_margin_threshold),
        "--known-am-indistinguishable-pairs",
        args.known_am_indistinguishable_pairs,
    ]

    run(["python3", str(score_script), *common, "--model-dir", str(Path(args.baseline_model_dir).resolve()), "--output-json", str(base_json), "--summary-json", str(base_summary), "--output-csv", str(base_csv)])
    run(["python3", str(score_script), *common, "--model-dir", str(Path(args.adapted_model_dir).resolve()), "--output-json", str(adap_json), "--summary-json", str(adap_summary), "--output-csv", str(adap_csv)])

    baseline_rows = load_rows(base_csv)
    adapted_rows = load_rows(adap_csv)

    baseline_summary = summarize_model(baseline_rows, ordered_pairs)
    adapted_summary = summarize_model(adapted_rows, ordered_pairs)
    delta = compare(baseline_summary, adapted_summary)

    report = {
        "runtime_root": str(runtime_root),
        "wav_dir": str(wav_dir),
        "baseline_model_dir": str(Path(args.baseline_model_dir).resolve()),
        "adapted_model_dir": str(Path(args.adapted_model_dir).resolve()),
        "fixed_pairs": [f"{a}/{b}" for a, b in fixed],
        "control_pairs": [f"{a}/{b}" for a, b in control],
        "baseline": baseline_summary,
        "adapted": adapted_summary,
        "comparison": delta,
    }

    report_json = exp_dir / "am_minpair_eval_report.json"
    report_md = exp_dir / "am_minpair_eval_report.md"
    report_json.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# T04 AM Minpair Baseline vs Adapted Report",
        "",
        f"- baseline_model_dir: `{report['baseline_model_dir']}`",
        f"- adapted_model_dir: `{report['adapted_model_dir']}`",
        f"- fixed_pairs: `{', '.join(report['fixed_pairs'])}`",
        f"- control_pairs: `{', '.join(report['control_pairs'])}`",
        "",
        "## Per-pair Comparison",
    ]
    for pair in report["comparison"]:
        c = report["comparison"][pair]
        lines.append(f"### {pair}")
        lines.append(
            f"- zero_margin_pct_among_ok (baseline -> adapted): `{c['baseline_zero_margin_pct_among_ok']}` -> `{c['adapted_zero_margin_pct_among_ok']}` (delta `{c['delta_zero_margin_pct']}`)"
        )
        lines.append(
            f"- status_ok_rate (baseline -> adapted): `{c['baseline_status_ok_rate']}` -> `{c['adapted_status_ok_rate']}`"
        )
        b = report["baseline"][pair]
        a = report["adapted"][pair]
        lines.append(f"- baseline decision counts: `{b['decision_counts']}`")
        lines.append(f"- adapted decision counts: `{a['decision_counts']}`")
        lines.append("")

    report_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    print(f"wrote baseline csv: {base_csv}")
    print(f"wrote adapted csv: {adap_csv}")
    print(f"wrote eval json: {report_json}")
    print(f"wrote eval md: {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
