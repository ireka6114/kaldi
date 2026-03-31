#!/usr/bin/env python3

import argparse
import csv
import json
import math
import shlex
import subprocess
import tempfile
from pathlib import Path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_kaldi_cmd(sh_cmd: str) -> tuple[bool, str]:
    proc = subprocess.run(["bash", "-lc", sh_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ok = proc.returncode == 0
    tail = (proc.stderr or "").strip().splitlines()
    return ok, (tail[-1] if tail else "")


def read_word_id_map(words_txt: Path) -> dict[str, str]:
    out = {}
    for line in words_txt.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            out[cols[1]] = cols[0]
    return out


def parse_key_map(path: Path) -> dict[str, list[str]]:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            out[cols[0]] = cols[1:]
    return out


def parse_float_map(path: Path) -> dict[str, float]:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            try:
                out[cols[0]] = float(cols[1])
            except ValueError:
                pass
    return out


def posterior_from_raw_costs(costs: dict[str, float | None]) -> dict[str, float | None]:
    usable = {k: v for k, v in costs.items() if v is not None}
    if not usable:
        return {k: None for k in costs}
    best = min(usable.values())
    exps = {k: math.exp(-(v - best)) for k, v in usable.items()}
    denom = sum(exps.values())
    return {k: (exps.get(k) / denom if k in exps and denom > 0.0 else None) for k in costs}


def decode_candidates(
    wav_path: Path,
    graph_dir: Path,
    words_txt: Path,
    model_dir: Path,
    s5_root: Path,
    nbest_n: int,
    acoustic_scale: float,
) -> tuple[str | None, str | None, dict[str, float | None]]:
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        spk2utt = tdir / "spk2utt"
        wav_scp = tdir / "wav.scp"
        lat_gz = tdir / "lat.1.gz"
        nbest_words = tdir / "nbest_words.txt"
        nbest_lm = tdir / "nbest_lm.txt"
        nbest_ac = tdir / "nbest_ac.txt"
        nbest_ali = tdir / "nbest_ali.txt"

        spk2utt.write_text("utt1 utt1\n", encoding="utf-8")
        wav_scp.write_text(f"utt1 {wav_path}\n", encoding="utf-8")

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
            "ark:" + str(spk2utt),
            "scp:" + str(wav_scp),
            "ark:|gzip -c >" + str(lat_gz),
        ]
        decode_sh = f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; " + " ".join(shlex.quote(x) for x in decode_cmd)
        ok, err = run_kaldi_cmd(decode_sh)
        if not ok:
            raise RuntimeError(err or "decode_failed")

        nbest_sh = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            f"lattice-to-nbest --n={nbest_n} 'ark:gunzip -c {lat_gz}|' ark:- "
            f"| nbest-to-linear ark:- ark,t:{nbest_ali} ark,t:{nbest_words} ark,t:{nbest_lm} ark,t:{nbest_ac}"
        )
        ok, err = run_kaldi_cmd(nbest_sh)
        if not ok:
            raise RuntimeError(err or "nbest_failed")

        id2word = read_word_id_map(words_txt)
        words_map = parse_key_map(nbest_words)
        lm_map = parse_float_map(nbest_lm)
        ac_map = parse_float_map(nbest_ac)

        ranked: list[tuple[str, float]] = []
        for key, ids in words_map.items():
            if not ids:
                continue
            word = id2word.get(ids[0], ids[0])
            if key in lm_map and key in ac_map:
                ranked.append((word, lm_map[key] + ac_map[key]))

        best = None
        runner_up = None
        if ranked:
            ranked.sort(key=lambda x: x[1])
            best = ranked[0][0]
            runner_up = ranked[1][0] if len(ranked) > 1 else None

        raw_costs: dict[str, float | None] = {}
        for word, cost in ranked:
            if word not in raw_costs:
                raw_costs[word] = cost
        return best, runner_up, raw_costs


def classify_error(entry: dict, best_candidate: str | None, decision: str) -> str:
    if decision == "accept":
        return "none"
    if decision == "uncertain":
        return "uncertain_margin"
    if best_candidate == entry.get("whole_word"):
        return "whole_word_dominance"
    if best_candidate == entry.get("deleted_part"):
        return "deleted_part_only_response"
    if best_candidate:
        return "failed_deletion"
    return "missing_decode"


def main() -> int:
    ap = argparse.ArgumentParser(description="Shared scorer for ELISION_EN_CORE probe graphs.")
    ap.add_argument("--runtime-root", default="egs/elision_en_core/s5/runtime")
    ap.add_argument("--probe-manifest", default="egs/elision_en_core/s5/runtime/manifests/elision_probe_manifest.json")
    ap.add_argument("--trial-manifest", required=True)
    ap.add_argument("--model-dir", default="")
    ap.add_argument("--output-json", required=True)
    ap.add_argument("--output-csv", required=True)
    ap.add_argument("--error-item-ids-out", default="")
    ap.add_argument("--margin-threshold", type=float, default=0.0)
    ap.add_argument("--acoustic-scale", type=float, default=0.1)
    args = ap.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    s5_root = runtime_root.parent
    probe_entries = {e["graph_name"]: e for e in read_json(Path(args.probe_manifest).resolve())["entries"]}
    trial_manifest = read_json(Path(args.trial_manifest).resolve())
    model_dir = Path(args.model_dir).resolve() if args.model_dir else Path(read_json(runtime_root / "manifests" / "elision_model_manifest.json")["model_dir"]).resolve()

    results = []
    csv_rows = []
    error_item_ids = []

    for trial in trial_manifest.get("entries", []):
        entry = probe_entries[trial["graph_name"]]
        graph_dir = Path(entry["graph_dir"]).resolve()
        words_txt = Path(entry["lang_graph_path"]).resolve() / "words.txt"

        best_candidate = None
        runner_up_candidate = None
        raw_costs = {}
        notes = []
        try:
            best_candidate, runner_up_candidate, raw_costs = decode_candidates(
                wav_path=Path(trial["wav_path"]).resolve(),
                graph_dir=graph_dir,
                words_txt=words_txt,
                model_dir=model_dir,
                s5_root=s5_root,
                nbest_n=max(8, len(entry["candidate_words"]) + 2),
                acoustic_scale=args.acoustic_scale,
            )
        except RuntimeError as exc:
            notes.append(str(exc))

        target_cost = raw_costs.get(entry["target_word"])
        comp_words = [w for w in entry["candidate_words"] if w != entry["target_word"]]
        best_comp = None
        best_comp_cost = None
        for word in comp_words:
            cost = raw_costs.get(word)
            if cost is None:
                continue
            if best_comp is None or cost < best_comp_cost:
                best_comp = word
                best_comp_cost = cost

        raw_margin = None
        if target_cost is not None and best_comp_cost is not None:
            raw_margin = best_comp_cost - target_cost

        if target_cost is None:
            decision = "missing_score"
        elif raw_margin is None:
            decision = "uncertain"
        elif raw_margin > args.margin_threshold:
            decision = "accept"
        elif raw_margin < -args.margin_threshold:
            decision = "reject"
        else:
            decision = "uncertain"

        error_type = classify_error(entry, best_candidate, decision)
        if decision in {"reject", "uncertain", "missing_score"}:
            error_item_ids.append(trial["item_id"])

        result = {
            "utt_id": trial["utt_id"],
            "task_id": trial["task_id"],
            "item_id": trial["item_id"],
            "group": entry["group"],
            "graph_name": trial["graph_name"],
            "probe_type": entry["probe_type"],
            "comparison_scope": entry["comparison_scope"],
            "best_candidate": best_candidate,
            "runner_up_candidate": runner_up_candidate,
            "target_cost": target_cost,
            "best_competitor_cost": best_comp_cost,
            "raw_margin": raw_margin,
            "decision": decision,
            "error_type": error_type,
            "candidate_posteriors": posterior_from_raw_costs({w: raw_costs.get(w) for w in entry["candidate_words"]}),
            "notes": notes,
        }
        results.append(result)
        csv_rows.append(
            {
                "utt_id": trial["utt_id"],
                "task_id": trial["task_id"],
                "item_id": trial["item_id"],
                "group": entry["group"],
                "graph_name": trial["graph_name"],
                "probe_type": entry["probe_type"],
                "best_candidate": best_candidate or "",
                "runner_up_candidate": runner_up_candidate or "",
                "target_cost": "" if target_cost is None else f"{target_cost:.6f}",
                "best_competitor_cost": "" if best_comp_cost is None else f"{best_comp_cost:.6f}",
                "raw_margin": "" if raw_margin is None else f"{raw_margin:.6f}",
                "decision": decision,
                "error_type": error_type,
                "comparison_scope": entry["comparison_scope"],
            }
        )

    out = {
        "task_id": trial_manifest["task_id"],
        "core_task_id": "ELISION_EN_CORE",
        "results": results,
        "error_item_ids": sorted(set(error_item_ids)),
    }
    Path(args.output_json).write_text(json.dumps(out, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    with Path(args.output_csv).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "utt_id",
                "task_id",
                "item_id",
                "group",
                "graph_name",
                "probe_type",
                "best_candidate",
                "runner_up_candidate",
                "target_cost",
                "best_competitor_cost",
                "raw_margin",
                "decision",
                "error_type",
                "comparison_scope",
            ],
        )
        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)

    if args.error_item_ids_out:
        Path(args.error_item_ids_out).write_text(
            json.dumps(sorted(set(error_item_ids)), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
