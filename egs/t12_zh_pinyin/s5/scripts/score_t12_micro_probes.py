#!/usr/bin/env python3

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProbeScore:
    utterance_id: str
    target_word: str
    parent_level_graph: str
    probe_graph_name: str
    probe_type: str
    diagnostic_dimension: str
    decision: str
    best_candidate: str | None
    runner_up_candidate: str | None
    target_cost: float | None
    best_competitor_cost: float | None
    raw_margin: float | None
    margin_threshold: float
    candidate_costs: dict[str, float | None]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def as_float_dict(raw: dict[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def derive_probe_result(
    utterance_id: str,
    parent_level_graph: str,
    target_word: str,
    probe: dict[str, Any],
    costs: dict[str, float],
    margin_threshold: float,
) -> ProbeScore:
    candidates = [str(x) for x in probe.get("candidate_words", [])]
    probe_costs = {w: costs.get(w) for w in candidates}

    target_cost = probe_costs.get(target_word)
    comp_candidates = [w for w in candidates if w != target_word and probe_costs.get(w) is not None]

    best_candidate = None
    runner_up_candidate = None
    best_comp_cost = None
    raw_margin = None
    decision = "missing_score"

    ranked = sorted(
        [(w, c) for w, c in probe_costs.items() if c is not None],
        key=lambda x: x[1],
    )
    if ranked:
        best_candidate = ranked[0][0]
        if len(ranked) >= 2:
            runner_up_candidate = ranked[1][0]

    if target_cost is not None and comp_candidates:
        best_comp_word, best_comp_cost = min(
            ((w, probe_costs[w]) for w in comp_candidates),
            key=lambda x: x[1],  # type: ignore[arg-type]
        )
        runner_up_candidate = best_comp_word if best_candidate == target_word else runner_up_candidate
        raw_margin = best_comp_cost - target_cost
        if best_candidate == target_word and raw_margin >= margin_threshold:
            decision = "hit"
        elif best_candidate == target_word:
            decision = "uncertain"
        else:
            decision = "confused"

    return ProbeScore(
        utterance_id=utterance_id,
        target_word=target_word,
        parent_level_graph=parent_level_graph,
        probe_graph_name=str(probe.get("graph_name", "")),
        probe_type=str(probe.get("probe_type") or "unknown_probe"),
        diagnostic_dimension=str(
            probe.get("diagnostic_dimension_hint")
            or probe.get("diagnostic_dimension")
            or "unknown"
        ),
        decision=decision,
        best_candidate=best_candidate,
        runner_up_candidate=runner_up_candidate,
        target_cost=target_cost,
        best_competitor_cost=best_comp_cost,
        raw_margin=raw_margin,
        margin_threshold=margin_threshold,
        candidate_costs=probe_costs,
    )


def summarize(scores: list[ProbeScore]) -> dict[str, Any]:
    total = len(scores)
    by_probe: dict[str, list[ProbeScore]] = defaultdict(list)
    for s in scores:
        by_probe[s.probe_type].append(s)

    probe_stats = {}
    confusion = Counter()
    decision_stats = Counter([s.decision for s in scores])
    for s in scores:
        if s.decision == "confused" and s.best_candidate:
            confusion[(s.target_word, s.best_candidate, s.probe_type)] += 1

    for probe_type, xs in sorted(by_probe.items()):
        n = len(xs)
        hit = sum(1 for x in xs if x.decision == "hit")
        confused = sum(1 for x in xs if x.decision == "confused")
        uncertain = sum(1 for x in xs if x.decision == "uncertain")
        missing = sum(1 for x in xs if x.decision == "missing_score")
        margins = [x.raw_margin for x in xs if x.raw_margin is not None]
        probe_stats[probe_type] = {
            "count": n,
            "hit_count": hit,
            "hit_rate": (hit / n) if n else 0.0,
            "confused_count": confused,
            "uncertain_count": uncertain,
            "missing_score_count": missing,
            "avg_raw_margin": (sum(margins) / len(margins)) if margins else None,
        }

    return {
        "total_probe_evaluations": total,
        "decision_stats": dict(decision_stats),
        "probe_type_stats": probe_stats,
        "major_probe_confusions": [
            {
                "target_word": t,
                "best_candidate": b,
                "probe_type": p,
                "count": c,
            }
            for (t, b, p), c in confusion.most_common(20)
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Score T12 micro-probe diagnostics from decode-evidence JSON."
    )
    ap.add_argument("--runtime-root", default="")
    ap.add_argument("--probe-manifest", default="")
    ap.add_argument("--decode-evidence-json", required=True)
    ap.add_argument("--margin-threshold", type=float, default=0.0)
    ap.add_argument("--output-json", default="")
    ap.add_argument("--summary-json", default="")
    ap.add_argument("--output-csv", default="")
    args = ap.parse_args()

    runtime_root = (
        Path(args.runtime_root).resolve()
        if args.runtime_root
        else Path(__file__).resolve().parents[1] / "runtime"
    )
    probe_manifest_path = (
        Path(args.probe_manifest).resolve()
        if args.probe_manifest
        else runtime_root / "manifests" / "t12_probe_manifest.json"
    )
    evidence_path = Path(args.decode_evidence_json).resolve()

    out_root = runtime_root / "diagnostic"
    out_root.mkdir(parents=True, exist_ok=True)
    output_json = (
        Path(args.output_json).resolve()
        if args.output_json
        else out_root / "t12_micro_probe_results.json"
    )
    summary_json = (
        Path(args.summary_json).resolve()
        if args.summary_json
        else out_root / "t12_micro_probe_summary.json"
    )
    output_csv = (
        Path(args.output_csv).resolve()
        if args.output_csv
        else out_root / "t12_micro_probe_results.csv"
    )

    probe_entries = read_json(probe_manifest_path).get("entries", [])
    probes_by_target: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for probe in probe_entries:
        parent = str(probe.get("parent_level_graph") or "T12_FORMAL")
        target = str(probe.get("target_word") or "")
        if target:
            probes_by_target[(parent, target)].append(probe)

    evidence_items = read_json(evidence_path)
    if not isinstance(evidence_items, list):
        raise SystemExit("decode-evidence JSON must be a list")

    all_scores: list[ProbeScore] = []
    grouped_results = []

    for idx, item in enumerate(evidence_items):
        if not isinstance(item, dict):
            continue
        utterance_id = str(item.get("utterance_id") or f"utt_{idx:05d}")
        target_word = str(item.get("target_word") or "")
        if not target_word:
            continue
        parent_level_graph = str(item.get("parent_level_graph") or "T12_FORMAL")
        probes = probes_by_target.get((parent_level_graph, target_word), [])
        global_costs = as_float_dict(item.get("candidate_raw_costs"))
        per_probe_costs = item.get("probe_costs") if isinstance(item.get("probe_costs"), dict) else {}

        one_scores: list[dict[str, Any]] = []
        for probe in probes:
            graph_name = str(probe.get("graph_name"))
            costs = as_float_dict(per_probe_costs.get(graph_name)) if graph_name else {}
            if not costs:
                costs = global_costs
            scored = derive_probe_result(
                utterance_id=utterance_id,
                parent_level_graph=parent_level_graph,
                target_word=target_word,
                probe=probe,
                costs=costs,
                margin_threshold=args.margin_threshold,
            )
            all_scores.append(scored)
            one_scores.append(
                {
                    "probe_graph_name": scored.probe_graph_name,
                    "probe_type": scored.probe_type,
                    "diagnostic_dimension": scored.diagnostic_dimension,
                    "decision": scored.decision,
                    "best_candidate": scored.best_candidate,
                    "runner_up_candidate": scored.runner_up_candidate,
                    "target_cost": scored.target_cost,
                    "best_competitor_cost": scored.best_competitor_cost,
                    "raw_margin": scored.raw_margin,
                    "margin_threshold": scored.margin_threshold,
                    "candidate_raw_costs": scored.candidate_costs,
                }
            )
        grouped_results.append(
            {
                "utterance_id": utterance_id,
                "target_word": target_word,
                "parent_level_graph": parent_level_graph,
                "probes": one_scores,
            }
        )

    summary = summarize(all_scores)
    summary["formal_decision_criterion"] = "probe_local_raw_margin"
    summary["margin_threshold"] = args.margin_threshold
    summary["input_probe_manifest"] = str(probe_manifest_path)
    summary["input_decode_evidence_json"] = str(evidence_path)

    output_json.write_text(
        json.dumps({"results": grouped_results, "summary": summary}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "utterance_id",
                "target_word",
                "parent_level_graph",
                "probe_graph_name",
                "probe_type",
                "diagnostic_dimension",
                "decision",
                "best_candidate",
                "runner_up_candidate",
                "target_cost",
                "best_competitor_cost",
                "raw_margin",
                "margin_threshold",
            ],
        )
        writer.writeheader()
        for s in all_scores:
            writer.writerow(
                {
                    "utterance_id": s.utterance_id,
                    "target_word": s.target_word,
                    "parent_level_graph": s.parent_level_graph,
                    "probe_graph_name": s.probe_graph_name,
                    "probe_type": s.probe_type,
                    "diagnostic_dimension": s.diagnostic_dimension,
                    "decision": s.decision,
                    "best_candidate": s.best_candidate or "",
                    "runner_up_candidate": s.runner_up_candidate or "",
                    "target_cost": "" if s.target_cost is None else f"{s.target_cost:.6f}",
                    "best_competitor_cost": ""
                    if s.best_competitor_cost is None
                    else f"{s.best_competitor_cost:.6f}",
                    "raw_margin": "" if s.raw_margin is None else f"{s.raw_margin:.6f}",
                    "margin_threshold": f"{s.margin_threshold:.6f}",
                }
            )

    print(f"wrote micro-probe results: {output_json}")
    print(f"wrote micro-probe summary: {summary_json}")
    print(f"wrote micro-probe csv: {output_csv}")


if __name__ == "__main__":
    main()
