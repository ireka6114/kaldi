#!/usr/bin/env python3

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

DEFAULT_PAIR_LIST = "gop:gope,vop:vope,wot:wote,jop:jope,fot:fote,zot:zote,jope:jop"
DEFAULT_FIXED_PAIR_LIST = "gop:gope,vop:vope,wot:wote,jop:jope"


def parse_ordered_pairs(spec: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen = set()
    for part in (spec or "").split(","):
        p = part.strip()
        if not p:
            continue
        if ":" in p:
            a, b = [x.strip() for x in p.split(":", 1)]
        elif "/" in p:
            a, b = [x.strip() for x in p.split("/", 1)]
        else:
            continue
        if not a or not b or a == b:
            continue
        key = (a, b)
        if key not in seen:
            out.append(key)
            seen.add(key)
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


def as_int(v: str) -> int | None:
    f = as_float(v)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def pair_name(pair: tuple[str, str]) -> str:
    return f"{pair[0]}/{pair[1]}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build T04 vowel AM discriminability report from phone-level outputs.")
    ap.add_argument("--input-csv", default="egs/t04_en_constrained/s5/runtime/diagnostic/t04_micro_probe_results_ref_renamed.csv")
    ap.add_argument(
        "--output-json",
        default="egs/t04_en_constrained/s5/runtime/diagnostic/t04_vowel_am_discriminability_report.json",
    )
    ap.add_argument(
        "--output-md",
        default="egs/t04_en_constrained/s5/runtime/diagnostic/t04_vowel_am_discriminability_report.md",
    )
    ap.add_argument("--pair-list", default=DEFAULT_PAIR_LIST)
    ap.add_argument("--fixed-pair-list", default=DEFAULT_FIXED_PAIR_LIST)
    args = ap.parse_args()

    input_csv = Path(args.input_csv).resolve()
    output_json = Path(args.output_json).resolve()
    output_md = Path(args.output_md).resolve()

    ordered_pairs = parse_ordered_pairs(args.pair_list)
    fixed_pairs = set(parse_ordered_pairs(args.fixed_pair_list))

    rows_by_pair: dict[tuple[str, str], list[dict]] = {p: [] for p in ordered_pairs}

    with input_csv.open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("probe_type") or "") != "vowel_probe":
                continue
            key = ((r.get("target_word") or "").strip(), (r.get("best_competitor_candidate") or "").strip())
            if key in rows_by_pair:
                rows_by_pair[key].append(r)

    per_pair = {}
    indistinguishable_pairs = []
    separable_pairs = []

    zero_margin_duration_ratios = []
    for p in ordered_pairs:
        rows = rows_by_pair.get(p, [])
        ok_rows = [x for x in rows if (x.get("phone_level_evidence_status") or "") == "ok"]

        margins = [as_float(x.get("vowel_local_margin_phone_level", "")) for x in ok_rows]
        margins = [m for m in margins if m is not None]

        target_costs = [as_float(x.get("target_vowel_acoustic_cost", "")) for x in ok_rows]
        target_costs = [v for v in target_costs if v is not None]
        competitor_costs = [as_float(x.get("competitor_vowel_acoustic_cost", "")) for x in ok_rows]
        competitor_costs = [v for v in competitor_costs if v is not None]

        target_frames = [as_int(x.get("target_vowel_frames_phone_level", "")) for x in ok_rows]
        target_frames = [v for v in target_frames if v is not None]
        competitor_frames = [as_int(x.get("competitor_vowel_frames_phone_level", "")) for x in ok_rows]
        competitor_frames = [v for v in competitor_frames if v is not None]

        zero_margin_rows = [x for x in ok_rows if as_float(x.get("vowel_local_margin_phone_level", "")) == 0.0]
        for x in zero_margin_rows:
            dr = as_float(x.get("local_duration_ratio_phone_level", ""))
            if dr is not None:
                zero_margin_duration_ratios.append(dr)

        always_zero = bool(margins) and all(abs(m) == 0.0 for m in margins)
        has_nonzero = any(abs(m) > 0.0 for m in margins)

        name = pair_name(p)
        if always_zero:
            indistinguishable_pairs.append(name)
        if has_nonzero:
            separable_pairs.append(name)

        per_pair[name] = {
            "rows": len(rows),
            "ok_rows": len(ok_rows),
            "phone_level_evidence_status_counts": dict(Counter(x.get("phone_level_evidence_status", "") for x in rows)),
            "decision_detail_counts": dict(Counter(x.get("decision_detail", "") for x in rows)),
            "ok_margin_all_zero": always_zero,
            "ok_margin_has_nonzero": has_nonzero,
            "mean_target_vowel_acoustic_cost": (sum(target_costs) / len(target_costs)) if target_costs else None,
            "mean_competitor_vowel_acoustic_cost": (sum(competitor_costs) / len(competitor_costs)) if competitor_costs else None,
            "mean_target_vowel_frames_phone_level": (sum(target_frames) / len(target_frames)) if target_frames else None,
            "mean_competitor_vowel_frames_phone_level": (sum(competitor_frames) / len(competitor_frames)) if competitor_frames else None,
            "mean_vowel_local_margin_phone_level": (sum(margins) / len(margins)) if margins else None,
            "zero_margin_ok_rows": len(zero_margin_rows),
            "duration_signal_nontrivial_when_margin_zero": sum(
                1
                for x in zero_margin_rows
                if (lambda d: d is not None and abs(d - 1.0) >= 0.1)(
                    as_float(x.get("local_duration_ratio_phone_level", ""))
                )
            ),
        }

    fixed_names = [pair_name(p) for p in ordered_pairs if p in fixed_pairs]
    control_names = [pair_name(p) for p in ordered_pairs if p not in fixed_pairs]

    fixed_zero = [x for x in indistinguishable_pairs if x in fixed_names]
    fixed_sep = [x for x in separable_pairs if x in fixed_names]
    control_zero = [x for x in indistinguishable_pairs if x in control_names]
    control_sep = [x for x in separable_pairs if x in control_names]

    broader_or_specific = "pair_specific"
    if fixed_zero and not control_sep:
        broader_or_specific = "broader_am_limitation"
    elif fixed_zero and control_sep:
        broader_or_specific = "pair_specific_with_controls_separable"

    duration_signal_summary = {
        "zero_margin_rows_with_duration": len(zero_margin_duration_ratios),
        "zero_margin_rows_with_nontrivial_duration_signal": sum(
            1 for d in zero_margin_duration_ratios if abs(d - 1.0) >= 0.1
        ),
    }

    report = {
        "task_id": "T04_EN",
        "input_csv": str(input_csv),
        "pairs_of_interest": [pair_name(p) for p in ordered_pairs],
        "fixed_pairs": fixed_names,
        "control_pairs": control_names,
        "per_pair": per_pair,
        "conclusions": {
            "pairs_with_status_ok_but_margin_always_zero": indistinguishable_pairs,
            "pairs_with_nonzero_phone_level_margin": separable_pairs,
            "fixed_pairs_always_zero": fixed_zero,
            "fixed_pairs_separable": fixed_sep,
            "control_pairs_always_zero": control_zero,
            "control_pairs_separable": control_sep,
            "pair_specific_or_broader": broader_or_specific,
            "duration_signal_when_margin_zero": duration_signal_summary,
        },
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    lines = []
    lines.append("# T04 Vowel AM Discriminability Report")
    lines.append("")
    lines.append(f"- input_csv: `{input_csv}`")
    lines.append(f"- fixed_pairs: `{', '.join(fixed_names)}`")
    lines.append(f"- control_pairs: `{', '.join(control_names)}`")
    lines.append("")
    lines.append("## Key Answers")
    lines.append(
        "- pairs with `phone_level_evidence_status=ok` but `vowel_local_margin_phone_level` always 0: "
        f"`{', '.join(report['conclusions']['pairs_with_status_ok_but_margin_always_zero']) or '(none)'}`"
    )
    lines.append(
        "- pairs separable by phone-level margin (`!= 0` observed): "
        f"`{', '.join(report['conclusions']['pairs_with_nonzero_phone_level_margin']) or '(none)'}`"
    )
    lines.append(f"- pair-specific or broader: `{report['conclusions']['pair_specific_or_broader']}`")
    ds = report["conclusions"]["duration_signal_when_margin_zero"]
    lines.append(
        "- duration signal when margin=0: "
        f"rows_with_duration={ds['zero_margin_rows_with_duration']}, "
        f"nontrivial_duration_signal={ds['zero_margin_rows_with_nontrivial_duration_signal']}"
    )
    lines.append("")
    lines.append("## Pair Breakdown")
    for name in report["pairs_of_interest"]:
        s = per_pair[name]
        lines.append(f"### {name}")
        lines.append(f"- rows: `{s['rows']}`, ok_rows: `{s['ok_rows']}`")
        lines.append(f"- phone_level_evidence_status_counts: `{s['phone_level_evidence_status_counts']}`")
        lines.append(f"- decision_detail_counts: `{s['decision_detail_counts']}`")
        lines.append(f"- ok_margin_all_zero: `{s['ok_margin_all_zero']}`")
        lines.append(f"- ok_margin_has_nonzero: `{s['ok_margin_has_nonzero']}`")
        lines.append(
            f"- mean_target/competitor_vowel_acoustic_cost: `{s['mean_target_vowel_acoustic_cost']}` / `{s['mean_competitor_vowel_acoustic_cost']}`"
        )
        lines.append(
            f"- mean_target/competitor_vowel_frames_phone_level: `{s['mean_target_vowel_frames_phone_level']}` / `{s['mean_competitor_vowel_frames_phone_level']}`"
        )
        lines.append(f"- mean_vowel_local_margin_phone_level: `{s['mean_vowel_local_margin_phone_level']}`")
        lines.append(
            f"- zero_margin_ok_rows / nontrivial_duration_signal: `{s['zero_margin_ok_rows']}` / `{s['duration_signal_nontrivial_when_margin_zero']}`"
        )
        lines.append("")

    output_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote report json: {output_json}")
    print(f"wrote report md: {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
