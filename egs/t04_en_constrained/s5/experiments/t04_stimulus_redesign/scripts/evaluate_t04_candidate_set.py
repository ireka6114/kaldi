#!/usr/bin/env python3

import argparse
import json
from collections import Counter
from pathlib import Path


def pair_key(short_word: str, long_word: str) -> str:
    return f"{short_word}:{long_word}"


def flatten_pairs(candidate_pool: dict, mode: str) -> list[dict]:
    pairs = []
    if mode == "pilot":
        for rec in candidate_pool.get("suggested_pilot_set", {}).get("replacements", []):
            pairs.append(rec)
        return pairs

    for _k, block in candidate_pool.get("fixed_pair_replacements", {}).items():
        for rec in block.get("accepted", []):
            pairs.append(rec)
    return pairs


def template_type(word: str) -> str:
    if word.endswith("ing"):
        return "ING"
    if word.endswith("e"):
        return "CVCE"
    return "CVC"


def summarize_pair(rec: dict) -> dict:
    short_word = rec["short_word"]
    long_word = rec["long_word"]
    nearest_short = rec.get("nearest_real_short", [])
    nearest_long = rec.get("nearest_real_long", [])
    d_short = nearest_short[0]["distance"] if nearest_short else None
    d_long = nearest_long[0]["distance"] if nearest_long else None
    return {
        "pair": pair_key(short_word, long_word),
        "source_pair": rec.get("source_pair"),
        "short_word": short_word,
        "long_word": long_word,
        "short_template": template_type(short_word),
        "long_template": template_type(long_word),
        "nearest_real_distance_short": d_short,
        "nearest_real_distance_long": d_long,
        "char_trigram_score_short": rec.get("char_trigram_score_short"),
        "char_trigram_score_long": rec.get("char_trigram_score_long"),
        "retained": rec.get("retained", False),
        "reasons": rec.get("reasons", []),
    }


def evaluate(candidate_pool: dict, audit_report: dict, mode: str) -> dict:
    pair_records = [summarize_pair(x) for x in flatten_pairs(candidate_pool, mode)]
    controls = [summarize_pair(x) for x in candidate_pool.get("control_matched_candidates", {}).get("accepted", [])]

    tmpl_counts = Counter()
    nearest_short = []
    nearest_long = []
    for r in pair_records:
        tmpl_counts[r["short_template"]] += 1
        tmpl_counts[r["long_template"]] += 1
        if r["nearest_real_distance_short"] is not None:
            nearest_short.append(r["nearest_real_distance_short"])
        if r["nearest_real_distance_long"] is not None:
            nearest_long.append(r["nearest_real_distance_long"])

    all_counts = list(tmpl_counts.values())
    ratio = (max(all_counts) / min(all_counts)) if all_counts and min(all_counts) > 0 else None

    def mean(values: list[float]) -> float | None:
        return (sum(values) / len(values)) if values else None

    risks = []
    if not pair_records:
        risks.append("no_candidate_pairs")
    if ratio is None or ratio > 1.5:
        risks.append("template_imbalance")

    close_real_short = sum(1 for d in nearest_short if d is not None and d <= 1)
    close_real_long = sum(1 for d in nearest_long if d is not None and d <= 1)
    total_pairs = len(pair_records) or 1
    close_ratio = (close_real_short + close_real_long) / (2.0 * total_pairs)
    if close_ratio > 0.75:
        risks.append("high_real_word_proximity")

    source_coverage = Counter(r.get("source_pair") for r in pair_records)
    fixed_pairs = audit_report.get("findings", {}).get("problematic_pair_correlation", {}).get("problem_words", [])
    compatibility = {
        "has_replacements": len(pair_records) > 0,
        "has_controls": len(controls) > 0,
        "source_pair_coverage": dict(source_coverage),
        "problem_word_count_reference": len(fixed_pairs),
        "compatible_with_existing_t04_structure": len(pair_records) > 0 and len(controls) > 0,
    }

    return {
        "mode": mode,
        "n_replacement_pairs": len(pair_records),
        "n_control_pairs": len(controls),
        "template_balance": {
            "counts": dict(tmpl_counts),
            "max_to_min_ratio": ratio,
        },
        "real_word_proximity": {
            "mean_nearest_distance_short": mean(nearest_short),
            "mean_nearest_distance_long": mean(nearest_long),
            "close_distance_ratio_le1": close_ratio,
        },
        "minimal_pair_concentration": {
            "source_pair_coverage": dict(source_coverage),
            "max_candidates_per_source_pair": max(source_coverage.values()) if source_coverage else 0,
        },
        "predicted_risk_flags": risks,
        "compatibility": compatibility,
        "replacement_pairs": pair_records,
        "controls": controls,
    }


def write_markdown(path: Path, result: dict) -> None:
    lines = [
        "# T04 Candidate Set Evaluation",
        "",
        f"- mode: `{result['mode']}`",
        f"- n_replacement_pairs: `{result['n_replacement_pairs']}`",
        f"- n_control_pairs: `{result['n_control_pairs']}`",
        f"- template_balance: `{result['template_balance']}`",
        f"- real_word_proximity: `{result['real_word_proximity']}`",
        f"- risk_flags: `{', '.join(result['predicted_risk_flags']) or '(none)'}`",
        "",
        "## Source Coverage",
    ]
    cov = result["minimal_pair_concentration"]["source_pair_coverage"]
    if cov:
        for k, v in sorted(cov.items()):
            lines.append(f"- {k}: `{v}`")
    else:
        lines.append("- (none)")

    lines.extend(["", "## Pilot Replacements"])
    if result["replacement_pairs"]:
        for r in result["replacement_pairs"]:
            lines.append(
                f"- {r['short_word']}/{r['long_word']} (source={r.get('source_pair')}, nearest={r['nearest_real_distance_short']}/{r['nearest_real_distance_long']})"
            )
    else:
        lines.append("- (none)")

    lines.extend(["", "## Controls"])
    if result["controls"]:
        for r in result["controls"]:
            lines.append(f"- {r['short_word']}/{r['long_word']} ({','.join(r['reasons'])})")
    else:
        lines.append("- (none)")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline evaluator for T04 redesigned pseudoword candidate sets.")
    ap.add_argument("--candidate-pool-json", default="egs/t04_en_constrained/s5/experiments/t04_stimulus_redesign/candidates/t04_redesigned_candidate_pool.json")
    ap.add_argument("--audit-report-json", default="egs/t04_en_constrained/s5/experiments/t04_stimulus_redesign/reports/t04_pseudoword_theory_audit_report.json")
    ap.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    ap.add_argument("--output-json", default="egs/t04_en_constrained/s5/experiments/t04_stimulus_redesign/reports/t04_redesigned_candidate_eval.json")
    ap.add_argument("--output-md", default="egs/t04_en_constrained/s5/experiments/t04_stimulus_redesign/docs/t04_redesigned_candidate_eval.md")
    args = ap.parse_args()

    candidate_pool = json.loads(Path(args.candidate_pool_json).read_text(encoding="utf-8"))
    audit_report = json.loads(Path(args.audit_report_json).read_text(encoding="utf-8"))

    result = evaluate(candidate_pool, audit_report, args.mode)

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    write_markdown(Path(args.output_md), result)

    print(f"wrote candidate eval json: {out_json}")
    print(f"wrote candidate eval markdown: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
