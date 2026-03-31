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

from t04_phone_level_scoring import score_vowel_pair_phone_level


LEVEL_PLAN = [
    ("T04_CVC", 2),
    ("T04_CVCE", 2),
    ("T04_ING_A", 1),
    ("T04_ING_B", 1),
]

WHOLE_WORD_AUX_SUFFIX = {
    "family_safe_whole_word": "FAMILY_SAFE",
    "free_decode_level_all": "LEVEL_ALL",
}

DEFAULT_AM_INDISTINGUISHABLE_PAIRS = "gop:gope,vop:vope,wot:wote,jop:jope"


@dataclass
class DecodeEvidence:
    best_candidate: str | None
    runner_up_candidate: str | None
    candidate_raw_costs: dict[str, float | None]
    candidate_norm_scores: dict[str, float | None]
    candidate_frames: dict[str, int | None]
    candidate_phone_sequences: dict[str, list[str]]
    candidate_posteriors: dict[str, float | None]
    acoustic_scale: float
    phone_alignment_available: bool
    diagnostic_phone_span_available: bool
    phone_alignment_summary: dict
    arc_post_available: bool
    arc_post_summary: dict
    notes: list[str]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_pair_set(spec: str) -> set[frozenset[str]]:
    out: set[frozenset[str]] = set()
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
        if a and b and a != b:
            out.add(frozenset({a, b}))
    return out


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


def run_kaldi_cmd(sh_cmd: str) -> tuple[bool, str]:
    proc = subprocess.run(
        ["bash", "-lc", sh_cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ok = proc.returncode == 0
    tail = (proc.stderr or "").strip().splitlines()
    tail_msg = tail[-1] if tail else ""
    return ok, tail_msg


def read_word_id_map(words_txt: Path) -> dict[str, str]:
    m = {}
    for line in words_txt.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            m[parts[1]] = parts[0]
    return m


def read_phone_id_map(phones_txt: Path) -> dict[str, str]:
    m = {}
    for line in phones_txt.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            m[cols[1]] = cols[0]
    return m


def parse_key_map(path: Path) -> dict[str, list[str]]:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            out[cols[0]] = cols[1:]
    return out


def parse_nbest(
    words_txt_path: Path,
    lm_costs_path: Path,
    ac_costs_path: Path,
    ali_txt_path: Path,
    id2word: dict[str, str],
    max_n: int,
) -> tuple[list[str], list[str], list[float], list[int | None]]:
    words_lines = words_txt_path.read_text(encoding="utf-8").splitlines() if words_txt_path.exists() else []
    lm_lines = lm_costs_path.read_text(encoding="utf-8").splitlines() if lm_costs_path.exists() else []
    ac_lines = ac_costs_path.read_text(encoding="utf-8").splitlines() if ac_costs_path.exists() else []
    ali_lines = ali_txt_path.read_text(encoding="utf-8").splitlines() if ali_txt_path.exists() else []

    key_to_lm: dict[str, float] = {}
    for line in lm_lines:
        cols = line.strip().split()
        if len(cols) < 2:
            continue
        try:
            key_to_lm[cols[0]] = float(cols[1])
        except Exception:
            continue

    key_to_ac: dict[str, float] = {}
    for line in ac_lines:
        cols = line.strip().split()
        if len(cols) < 2:
            continue
        try:
            key_to_ac[cols[0]] = float(cols[1])
        except Exception:
            continue

    key_to_frames: dict[str, int] = {}
    for line in ali_lines:
        cols = line.strip().split()
        if len(cols) < 2:
            continue
        key_to_frames[cols[0]] = len(cols) - 1

    keys: list[str] = []
    cands: list[str] = []
    costs: list[float] = []
    frames: list[int | None] = []
    seen = set()
    for line in words_lines:
        cols = line.strip().split()
        if len(cols) < 2:
            continue
        key = cols[0]
        words = [id2word.get(tok, tok) for tok in cols[1:]]
        cand = " ".join(words).strip()
        if not cand or cand in seen:
            continue
        seen.add(cand)
        keys.append(key)
        cands.append(cand)
        lm = key_to_lm.get(key, math.nan)
        ac = key_to_ac.get(key, math.nan)
        costs.append((lm + ac) if (not math.isnan(lm) and not math.isnan(ac)) else math.nan)
        frames.append(key_to_frames.get(key))
        if len(cands) >= max_n:
            break
    return keys, cands, costs, frames


def normalize_scores(cands: list[str], costs: list[float], frames: list[int | None]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for cand, cost, frame_count in zip(cands, costs, frames):
        if frame_count is None or frame_count <= 0 or math.isnan(cost):
            out[cand] = None
            continue
        out[cand] = -cost / float(frame_count)
    return out


def raw_cost_map(cands: list[str], costs: list[float]) -> dict[str, float | None]:
    out = {}
    for cand, cost in zip(cands, costs):
        out[cand] = None if math.isnan(cost) else cost
    return out


def posterior_from_raw_costs(costs: dict[str, float | None]) -> dict[str, float | None]:
    usable = {k: v for k, v in costs.items() if v is not None}
    if not usable:
        return {k: None for k in costs}
    best = min(usable.values())
    vals = {k: math.exp(-(v - best)) for k, v in usable.items()}
    denom = sum(vals.values())
    out: dict[str, float | None] = {}
    for k in costs:
        out[k] = (vals.get(k) / denom) if (k in vals and denom > 0.0) else None
    return out


def summarize_phone_ctm(ctm_path: Path) -> dict:
    if not ctm_path.exists():
        return {"ctm_entries": 0, "mean_confidence": None}
    vals = []
    for line in ctm_path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) < 6:
            continue
        try:
            vals.append(float(cols[5]))
        except Exception:
            continue
    if not vals:
        return {"ctm_entries": 0, "mean_confidence": None}
    return {"ctm_entries": len(vals), "mean_confidence": sum(vals) / len(vals)}


def summarize_arc_post(arc_post_path: Path) -> dict:
    if not arc_post_path.exists():
        return {"arc_entries": 0, "mean_arc_posterior": None}
    vals = []
    for line in arc_post_path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) < 4:
            continue
        try:
            vals.append(float(cols[3]))
        except Exception:
            continue
    if not vals:
        return {"arc_entries": 0, "mean_arc_posterior": None}
    return {"arc_entries": len(vals), "mean_arc_posterior": sum(vals) / len(vals)}


def run_decode_constrained(
    wav_path: Path,
    graph_dir: Path,
    words_txt: Path,
    model_dir: Path,
    s5_root: Path,
    nbest_n: int,
    acoustic_scale: float,
) -> DecodeEvidence:
    notes = []
    final_mdl = model_dir / "final.mdl"
    online_conf = model_dir / "conf" / "online.conf"
    mfcc_conf = model_dir / "conf" / "mfcc.conf"
    iv_conf = model_dir / "conf" / "ivector_extractor.conf"
    word_boundary = graph_dir / "phones" / "word_boundary.int"
    phones_txt = graph_dir / "phones.txt"

    required = [
        (wav_path, "missing_wav"),
        (graph_dir / "HCLG.fst", "missing_hclg"),
        (words_txt, "missing_words_txt"),
        (final_mdl, "missing_final_mdl"),
        (online_conf, "missing_online_conf"),
        (mfcc_conf, "missing_mfcc_conf"),
        (iv_conf, "missing_ivector_extractor_conf"),
        (model_dir / "ivector_extractor", "missing_ivector_extractor"),
    ]
    missing = [tag for p, tag in required if not p.exists()]
    if missing:
        return DecodeEvidence(
            best_candidate=None,
            runner_up_candidate=None,
            candidate_raw_costs={},
            candidate_norm_scores={},
            candidate_frames={},
            candidate_phone_sequences={},
            candidate_posteriors={},
            acoustic_scale=acoustic_scale,
            phone_alignment_available=False,
            diagnostic_phone_span_available=False,
            phone_alignment_summary={"ctm_entries": 0, "mean_confidence": None},
            arc_post_available=False,
            arc_post_summary={"artifact_size_bytes": 0},
            notes=missing,
        )

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        spk2utt = tdir / "spk2utt"
        wav_scp = tdir / "wav.scp"
        lat_gz = tdir / "lat.1.gz"
        aligned_lat_gz = tdir / "lat.phone_aligned.1.gz"
        arc_post_txt = tdir / "arc_post.txt"
        nbest_words_txt = tdir / "nbest_words.txt"
        nbest_lm_txt = tdir / "nbest_lm.txt"
        nbest_ac_txt = tdir / "nbest_ac.txt"
        nbest_ali_txt = tdir / "nbest_ali.txt"
        nbest_phone_txt = tdir / "nbest_phone_frames.txt"
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
            f"--acoustic-scale={acoustic_scale}",
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
            return DecodeEvidence(
                best_candidate=None,
                runner_up_candidate=None,
                candidate_raw_costs={},
                candidate_norm_scores={},
                candidate_frames={},
                candidate_phone_sequences={},
                candidate_posteriors={},
                acoustic_scale=acoustic_scale,
                phone_alignment_available=False,
                diagnostic_phone_span_available=False,
                phone_alignment_summary={"ctm_entries": 0, "mean_confidence": None},
                arc_post_available=False,
                arc_post_summary={"artifact_size_bytes": 0},
                notes=notes,
            )

        nbest_cmd = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            f"lattice-to-nbest --n={nbest_n} 'ark:gunzip -c {lat_gz}|' ark:- "
            f"| nbest-to-linear ark:- ark,t:{nbest_ali_txt} ark,t:{nbest_words_txt} ark,t:{nbest_lm_txt} ark,t:{nbest_ac_txt}"
        )
        run_kaldi_cmd(nbest_cmd)

        ali_phone_sh = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            f"ali-to-phones --per-frame=true {shlex.quote(str(final_mdl))} "
            f"ark,t:{nbest_ali_txt} ark,t:{nbest_phone_txt}"
        )
        run_kaldi_cmd(ali_phone_sh)

        id2word = read_word_id_map(words_txt)
        keys, cands, costs, frames = parse_nbest(
            nbest_words_txt,
            nbest_lm_txt,
            nbest_ac_txt,
            nbest_ali_txt,
            id2word,
            max_n=nbest_n,
        )
        phone_id_map = read_phone_id_map(phones_txt) if phones_txt.exists() else {}
        key_phone_ids = parse_key_map(nbest_phone_txt)
        phone_sequences: dict[str, list[str]] = {}
        for key, cand in zip(keys, cands):
            seq_ids = key_phone_ids.get(key, [])
            phone_sequences[cand] = [phone_id_map.get(pid, pid) for pid in seq_ids]

        raw_costs = raw_cost_map(cands, costs)
        norm_scores = normalize_scores(cands, costs, frames)
        frame_map = {c: f for c, f in zip(cands, frames)}
        all_posteriors = posterior_from_raw_costs(raw_costs)

        ranked = sorted(
            [c for c in cands if raw_costs.get(c) is not None],
            key=lambda c: raw_costs[c],  # type: ignore[index]
        )
        best = ranked[0] if ranked else (cands[0] if cands else None)
        runner_up = ranked[1] if len(ranked) > 1 else (cands[1] if len(cands) > 1 else None)

        phone_alignment_available = False
        diagnostic_phone_span_available = False
        phone_summary = {"ctm_entries": 0, "mean_confidence": None}
        if word_boundary.exists():
            align_sh = (
                f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
                f"lattice-align-phones {shlex.quote(str(final_mdl))} "
                f"'ark:gunzip -c {lat_gz}|' 'ark:|gzip -c >{aligned_lat_gz}'"
            )
            align_ok, _ = run_kaldi_cmd(align_sh)
            ctm_src = aligned_lat_gz if align_ok else lat_gz
            if align_ok and aligned_lat_gz.exists():
                phone_alignment_available = True
                notes.append("lattice_align_phones_ok")
            else:
                notes.append("lattice_align_phones_failed")

            ctm_sh = (
                f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
                f"lattice-to-ctm-conf --acoustic-scale={acoustic_scale} --word-boundary={shlex.quote(str(word_boundary))} "
                f"'ark:gunzip -c {ctm_src}|' {shlex.quote(str(ctm_conf))}"
            )
            ctm_ok, _ = run_kaldi_cmd(ctm_sh)
            notes.append("lattice_to_ctm_conf_ok" if ctm_ok else "lattice_to_ctm_conf_failed")
            if ctm_ok:
                phone_summary = summarize_phone_ctm(ctm_conf)
                diagnostic_phone_span_available = phone_summary.get("ctm_entries", 0) > 0
        else:
            notes.append("missing_word_boundary_for_ctm")

        arc_post_sh = (
            f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
            f"lattice-arc-post --acoustic-scale={acoustic_scale} {shlex.quote(str(final_mdl))} "
            f"'ark:gunzip -c {lat_gz}|' {shlex.quote(str(arc_post_txt))}"
        )
        arc_ok, _ = run_kaldi_cmd(arc_post_sh)
        arc_post_available = arc_ok and arc_post_txt.exists()
        arc_summary = summarize_arc_post(arc_post_txt)
        notes.append("lattice_arc_post_ok" if arc_post_available else "lattice_arc_post_failed")
        notes.append("decode_success")

        return DecodeEvidence(
            best_candidate=best,
            runner_up_candidate=runner_up,
            candidate_raw_costs=raw_costs,
            candidate_norm_scores=norm_scores,
            candidate_frames=frame_map,
            candidate_phone_sequences=phone_sequences,
            candidate_posteriors=all_posteriors,
            acoustic_scale=acoustic_scale,
            phone_alignment_available=phone_alignment_available,
            diagnostic_phone_span_available=diagnostic_phone_span_available,
            phone_alignment_summary=phone_summary,
            arc_post_available=arc_post_available,
            arc_post_summary=arc_summary,
            notes=notes,
        )


def derived_probe_softmax(costs: dict[str, float | None]) -> dict[str, float | None]:
    usable = {k: v for k, v in costs.items() if v is not None}
    if not usable:
        return {k: None for k in costs}
    best = min(usable.values())
    exps = {k: math.exp(-(v - best)) for k, v in usable.items()}
    denom = sum(exps.values())
    out: dict[str, float | None] = {}
    for k in costs:
        out[k] = (exps.get(k) / denom) if (k in exps and denom > 0.0) else None
    return out


def probe_dimension_judgement(probe_type: str, decision: str) -> str:
    if decision in {"uncertain", "missing_score"}:
        return "uncertain"
    if probe_type == "onset_probe":
        return "onset_substitution" if decision == "reject" else "onset_ok"
    if probe_type == "vowel_probe":
        return "vowel_length_error" if decision == "reject" else "vowel_length_ok"
    if probe_type == "pattern_probe":
        return "ing_doubling_error" if decision == "reject" else "ing_doubling_ok"
    return "unknown"


def diagnostic_span(seq: list[str], probe_type: str) -> tuple[int | None, int | None, int]:
    if not seq:
        return None, None, 0
    if probe_type == "vowel_probe":
        idx = next((i for i, p in enumerate(seq) if p in {"O_SHORT_I", "O_LONG_I"}), None)
        if idx is None:
            return None, None, 0
        j = idx
        while j + 1 < len(seq) and seq[j + 1] == seq[idx]:
            j += 1
        return idx, j, j - idx + 1

    if probe_type == "pattern_probe":
        v_idx = next((i for i, p in enumerate(seq) if p in {"O_SHORT_I", "O_LONG_I"}), None)
        ih_idx = next((i for i, p in enumerate(seq) if p.startswith("IH_")), None)
        if v_idx is None or ih_idx is None or ih_idx <= v_idx:
            return None, None, 0
        s = v_idx + 1
        e = ih_idx - 1
        if e < s:
            return None, None, 0
        return s, e, e - s + 1

    return None, None, 0


def _extract_probe_pair_vowel_side(ev: DecodeEvidence, word: str) -> dict:
    out = {
        "status": "no_alignment",
        "notes": [],
        "total_cost": None,
        "total_frames": None,
        "vowel_frames": None,
        "vowel_phone": None,
        "vowel_cost": None,
        "vowel_avg_cost_per_frame": None,
    }
    out["notes"] = list(ev.notes)
    total_cost = ev.candidate_raw_costs.get(word)
    total_frames = ev.candidate_frames.get(word)
    seq = ev.candidate_phone_sequences.get(word, [])
    out["total_cost"] = total_cost
    out["total_frames"] = total_frames
    if not seq:
        return out

    s, _, vf = diagnostic_span(seq, "vowel_probe")
    if vf <= 0 or s is None:
        out["status"] = "no_vowel_span"
        return out
    out["vowel_frames"] = vf
    out["vowel_phone"] = seq[s]

    if total_cost is None or total_frames is None or total_frames <= 0:
        out["status"] = "no_alignment"
        return out

    avg = total_cost / float(total_frames)
    out["vowel_avg_cost_per_frame"] = avg
    out["vowel_cost"] = avg * vf
    out["status"] = "ok"
    return out


def extract_vowel_local_evidence_from_probe(
    target_word: str,
    competitor_word: str | None,
    probe_evidence: DecodeEvidence,
) -> dict:
    if not competitor_word:
        return {
            "local_evidence_status": "no_evidence",
            "local_margin_source": "missing_competitor_word",
            "local_duration_source": "missing_competitor_word",
        }

    t = _extract_probe_pair_vowel_side(probe_evidence, target_word)
    c = _extract_probe_pair_vowel_side(probe_evidence, competitor_word)

    status = "ok"
    if t["status"] == "no_alignment" or c["status"] == "no_alignment":
        status = "no_alignment"
    elif t["status"] == "no_vowel_span" or c["status"] == "no_vowel_span":
        status = "no_vowel_span"

    local_duration_ratio = None
    if t.get("vowel_frames") and c.get("vowel_frames"):
        local_duration_ratio = t["vowel_frames"] / float(c["vowel_frames"])

    vowel_local_margin = None
    vowel_norm_margin = None
    if t.get("vowel_cost") is not None and c.get("vowel_cost") is not None:
        vowel_local_margin = c["vowel_cost"] - t["vowel_cost"]
    if t.get("vowel_avg_cost_per_frame") is not None and c.get("vowel_avg_cost_per_frame") is not None:
        vowel_norm_margin = c["vowel_avg_cost_per_frame"] - t["vowel_avg_cost_per_frame"]

    return {
        "local_evidence_status": status,
        "local_margin_source": "pairwise_probe_vowel_cost_from_total_cost_per_frame"
        if status == "ok"
        else f"unavailable_{status}",
        "local_duration_source": "pairwise_probe_vowel_span_ratio" if local_duration_ratio is not None else f"unavailable_{status}",
        "target_vowel_frames": t.get("vowel_frames"),
        "competitor_vowel_frames": c.get("vowel_frames"),
        "target_vowel_cost": t.get("vowel_cost"),
        "competitor_vowel_cost": c.get("vowel_cost"),
        "target_vowel_avg_cost_per_frame": t.get("vowel_avg_cost_per_frame"),
        "competitor_vowel_avg_cost_per_frame": c.get("vowel_avg_cost_per_frame"),
        "vowel_local_margin": vowel_local_margin,
        "vowel_norm_margin": vowel_norm_margin,
        "local_duration_ratio": local_duration_ratio,
        "target_vowel_phone": t.get("vowel_phone"),
        "competitor_vowel_phone": c.get("vowel_phone"),
        "target_local_notes": t.get("notes"),
        "competitor_local_notes": c.get("notes"),
    }


def build_vowel_local_evidence(
    *,
    runtime_root: Path,
    s5_root: Path,
    model_dir: Path,
    wav_path: Path,
    target_word: str,
    competitor_word: str | None,
    probe_evidence: DecodeEvidence,
    acoustic_scale: float,
) -> dict:
    proxy = extract_vowel_local_evidence_from_probe(
        target_word=target_word,
        competitor_word=competitor_word,
        probe_evidence=probe_evidence,
    )
    if not competitor_word:
        proxy["local_score_mode"] = "proxy_from_probe_total_cost_per_frame"
        proxy["phone_level_evidence_status"] = "missing_competitor_word"
        proxy["target_vowel_cost_source"] = proxy.get("local_margin_source")
        proxy["competitor_vowel_cost_source"] = proxy.get("local_margin_source")
        proxy["target_vowel_acoustic_cost"] = None
        proxy["competitor_vowel_acoustic_cost"] = None
        proxy["vowel_local_margin_phone_level"] = None
        proxy["target_vowel_frames_phone_level"] = None
        proxy["competitor_vowel_frames_phone_level"] = None
        return proxy

    phone_pair = score_vowel_pair_phone_level(
        runtime_root=runtime_root,
        s5_root=s5_root,
        model_dir=model_dir,
        wav_path=wav_path,
        target_word=target_word,
        competitor_word=competitor_word,
        acoustic_scale=acoustic_scale,
    )
    target = phone_pair.get("target", {})
    competitor = phone_pair.get("competitor", {})
    if phone_pair.get("status") == "ok":
        return {
            "local_evidence_status": "ok",
            "local_margin_source": "phone_level_forced_align_vowel_acoustic_cost",
            "local_duration_source": "phone_level_forced_align_vowel_span_ratio"
            if phone_pair.get("local_duration_ratio_phone_level") is not None
            else "unavailable_phone_level_duration",
            "local_score_mode": "forced_align_phone_level",
            "phone_level_evidence_status": phone_pair.get("phone_level_evidence_status", "ok"),
            "target_vowel_frames": target.get("vowel_frames"),
            "competitor_vowel_frames": competitor.get("vowel_frames"),
            "target_vowel_frames_phone_level": target.get("vowel_frames"),
            "competitor_vowel_frames_phone_level": competitor.get("vowel_frames"),
            "target_vowel_cost": target.get("vowel_acoustic_cost"),
            "competitor_vowel_cost": competitor.get("vowel_acoustic_cost"),
            "target_vowel_acoustic_cost": target.get("vowel_acoustic_cost"),
            "competitor_vowel_acoustic_cost": competitor.get("vowel_acoustic_cost"),
            "target_vowel_avg_cost_per_frame": target.get("vowel_avg_cost_per_frame"),
            "competitor_vowel_avg_cost_per_frame": competitor.get("vowel_avg_cost_per_frame"),
            "vowel_local_margin": phone_pair.get("vowel_local_margin_phone_level"),
            "vowel_local_margin_phone_level": phone_pair.get("vowel_local_margin_phone_level"),
            "vowel_norm_margin": None,
            "local_duration_ratio": phone_pair.get("local_duration_ratio_phone_level"),
            "local_duration_ratio_phone_level": phone_pair.get("local_duration_ratio_phone_level"),
            "target_vowel_phone": target.get("vowel_phone"),
            "competitor_vowel_phone": competitor.get("vowel_phone"),
            "target_vowel_cost_source": target.get("cost_source"),
            "competitor_vowel_cost_source": competitor.get("cost_source"),
            "target_local_notes": target.get("notes"),
            "competitor_local_notes": competitor.get("notes"),
        }

    proxy["local_score_mode"] = "proxy_from_probe_total_cost_per_frame"
    proxy["phone_level_evidence_status"] = phone_pair.get("phone_level_evidence_status", "unavailable")
    proxy["target_vowel_cost_source"] = proxy.get("local_margin_source")
    proxy["competitor_vowel_cost_source"] = proxy.get("local_margin_source")
    proxy["target_vowel_acoustic_cost"] = None
    proxy["competitor_vowel_acoustic_cost"] = None
    proxy["vowel_local_margin_phone_level"] = None
    proxy["local_duration_ratio_phone_level"] = None
    proxy["target_vowel_frames_phone_level"] = None
    proxy["competitor_vowel_frames_phone_level"] = None
    return proxy


def score_one_probe(
    target_word: str,
    probe: dict,
    evidence: DecodeEvidence,
    margin_threshold: float,
    small_margin_threshold: float,
    duration_threshold: float,
    local_vowel_evidence: dict | None = None,
    vowel_local_margin_threshold: float = 0.05,
    known_am_indistinguishable_pairs: set[frozenset[str]] | None = None,
) -> dict:
    cand_words = probe.get("candidate_words", [])
    probe_costs = {w: evidence.candidate_raw_costs.get(w) for w in cand_words}
    probe_norm = {w: evidence.candidate_norm_scores.get(w) for w in cand_words}
    probe_post = derived_probe_softmax(probe_costs)

    target_cost = probe_costs.get(target_word)
    comp_words = [w for w in cand_words if w != target_word]
    best_comp = None
    best_comp_cost = None
    for w in comp_words:
        c = probe_costs.get(w)
        if c is None:
            continue
        if best_comp is None or c < best_comp_cost:  # type: ignore[operator]
            best_comp = w
            best_comp_cost = c

    raw_margin = None
    if target_cost is not None and best_comp_cost is not None:
        raw_margin = best_comp_cost - target_cost
    whole_word_margin = raw_margin

    margin_source = "measured_competitor_minus_target"
    if target_cost is None:
        margin_source = "missing_target_cost"
        decision = "missing_score"
    elif raw_margin is None:
        margin_source = "missing_competitor_cost"
        decision = "uncertain"
    elif raw_margin > margin_threshold:
        decision = "accept"
    elif raw_margin < -margin_threshold:
        decision = "reject"
    else:
        decision = "uncertain"

    probe_type = probe.get("probe_type") or "unknown_probe"
    target_seq = evidence.candidate_phone_sequences.get(target_word, [])
    comp_seq = evidence.candidate_phone_sequences.get(best_comp, []) if best_comp else []
    t_s, t_e, t_frames = diagnostic_span(target_seq, probe_type)
    c_s, c_e, c_frames = diagnostic_span(comp_seq, probe_type)
    duration_ratio = None
    duration_source = "missing_phone_span"
    if t_frames > 0 and c_frames > 0:
        duration_ratio = t_frames / float(c_frames)
        duration_source = "measured_phone_span_ratio"

    duration_fallback_triggered = False
    duration_decision = "not_triggered"
    local_phone_margin = None
    if raw_margin is not None and t_frames > 0 and c_frames > 0:
        local_phone_margin = raw_margin / (0.5 * (t_frames + c_frames))
    if probe_type in {"vowel_probe", "pattern_probe"} and raw_margin is not None:
        if abs(raw_margin) < small_margin_threshold:
            duration_fallback_triggered = True
            if duration_ratio is None:
                duration_decision = "insufficient_duration_evidence"
            elif duration_ratio >= duration_threshold:
                duration_decision = "accept"
                decision = "accept"
            elif duration_ratio <= (1.0 / duration_threshold):
                duration_decision = "reject"
                decision = "reject"
            else:
                duration_decision = "uncertain"
                decision = "uncertain"

    local_evidence_status = "not_applicable"
    local_margin_source = "not_applicable"
    local_duration_source = "not_applicable"
    target_vowel_frames = None
    competitor_vowel_frames = None
    target_vowel_cost = None
    competitor_vowel_cost = None
    target_vowel_avg_cost_per_frame = None
    competitor_vowel_avg_cost_per_frame = None
    target_vowel_acoustic_cost = None
    competitor_vowel_acoustic_cost = None
    vowel_local_margin = None
    vowel_local_margin_phone_level = None
    vowel_norm_margin = None
    local_duration_ratio = None
    local_duration_ratio_phone_level = None
    target_vowel_phone = None
    competitor_vowel_phone = None
    local_score_mode = "not_applicable"
    phone_level_evidence_status = "not_applicable"
    target_vowel_cost_source = None
    competitor_vowel_cost_source = None
    target_vowel_frames_phone_level = None
    competitor_vowel_frames_phone_level = None
    am_indistinguishable_pair_guard_applied = False

    if probe_type == "vowel_probe":
        if local_vowel_evidence:
            local_evidence_status = local_vowel_evidence.get("local_evidence_status", "no_evidence")
            local_margin_source = local_vowel_evidence.get("local_margin_source", "unknown")
            local_duration_source = local_vowel_evidence.get("local_duration_source", "unknown")
            local_score_mode = local_vowel_evidence.get("local_score_mode", "unknown")
            phone_level_evidence_status = local_vowel_evidence.get("phone_level_evidence_status", "unknown")
            target_vowel_frames = local_vowel_evidence.get("target_vowel_frames")
            competitor_vowel_frames = local_vowel_evidence.get("competitor_vowel_frames")
            target_vowel_frames_phone_level = local_vowel_evidence.get("target_vowel_frames_phone_level")
            competitor_vowel_frames_phone_level = local_vowel_evidence.get("competitor_vowel_frames_phone_level")
            target_vowel_cost = local_vowel_evidence.get("target_vowel_cost")
            competitor_vowel_cost = local_vowel_evidence.get("competitor_vowel_cost")
            target_vowel_acoustic_cost = local_vowel_evidence.get("target_vowel_acoustic_cost")
            competitor_vowel_acoustic_cost = local_vowel_evidence.get("competitor_vowel_acoustic_cost")
            target_vowel_cost_source = local_vowel_evidence.get("target_vowel_cost_source")
            competitor_vowel_cost_source = local_vowel_evidence.get("competitor_vowel_cost_source")
            target_vowel_avg_cost_per_frame = local_vowel_evidence.get("target_vowel_avg_cost_per_frame")
            competitor_vowel_avg_cost_per_frame = local_vowel_evidence.get("competitor_vowel_avg_cost_per_frame")
            vowel_local_margin = local_vowel_evidence.get("vowel_local_margin")
            vowel_local_margin_phone_level = local_vowel_evidence.get("vowel_local_margin_phone_level")
            vowel_norm_margin = local_vowel_evidence.get("vowel_norm_margin")
            local_duration_ratio = local_vowel_evidence.get("local_duration_ratio")
            local_duration_ratio_phone_level = local_vowel_evidence.get("local_duration_ratio_phone_level")
            target_vowel_phone = local_vowel_evidence.get("target_vowel_phone")
            competitor_vowel_phone = local_vowel_evidence.get("competitor_vowel_phone")
        else:
            local_evidence_status = "no_evidence"
            local_margin_source = "missing_local_evidence_object"
            local_duration_source = "missing_local_evidence_object"
            local_score_mode = "missing_local_evidence_object"
            phone_level_evidence_status = "missing_local_evidence_object"

        use_phone_level = local_score_mode == "forced_align_phone_level" and phone_level_evidence_status == "ok"
        decision_margin = vowel_local_margin_phone_level if use_phone_level else vowel_local_margin
        decision_duration_ratio = local_duration_ratio_phone_level if use_phone_level else local_duration_ratio
        if local_evidence_status == "ok":
            pair_key = frozenset({target_word, best_comp}) if best_comp else None
            known_indistinguishable = bool(
                use_phone_level
                and pair_key is not None
                and known_am_indistinguishable_pairs
                and pair_key in known_am_indistinguishable_pairs
                and decision_margin is not None
                and abs(decision_margin) == 0.0
            )
            if known_indistinguishable:
                am_indistinguishable_pair_guard_applied = True
                if whole_word_margin is not None and abs(whole_word_margin) >= small_margin_threshold:
                    decision = "accept" if whole_word_margin > 0 else "reject"
                else:
                    decision = "uncertain"
                decision_detail = "am_indistinguishable_pair"
            elif (
                whole_word_margin is not None
                and decision_margin is not None
                and abs(whole_word_margin) >= small_margin_threshold
                and whole_word_margin * decision_margin < 0
            ):
                decision = "accept" if whole_word_margin > 0 else "reject"
                decision_detail = "whole_word_fallback"
            elif decision_margin is not None and decision_margin > vowel_local_margin_threshold:
                decision = "accept"
                decision_detail = "phone_level_margin_win" if use_phone_level else "local_margin_win"
            elif decision_margin is not None and decision_margin < -vowel_local_margin_threshold:
                decision = "reject"
                decision_detail = "phone_level_margin_win" if use_phone_level else "local_margin_win"
            elif decision_duration_ratio is not None:
                if decision_duration_ratio >= duration_threshold:
                    decision = "accept"
                    decision_detail = "phone_level_duration_win" if use_phone_level else "local_duration_win"
                elif decision_duration_ratio <= (1.0 / duration_threshold):
                    decision = "reject"
                    decision_detail = "phone_level_duration_win" if use_phone_level else "local_duration_win"
                else:
                    decision = "uncertain"
                    decision_detail = "uncertain_close_call"
            else:
                decision = "uncertain"
                decision_detail = "uncertain_no_evidence"
        else:
            if decision == "missing_score":
                decision_detail = "uncertain_no_evidence"
                decision = "uncertain"
            elif decision in {"accept", "reject"}:
                decision_detail = "whole_word_fallback"
            else:
                decision_detail = "uncertain_no_evidence" if margin_source.startswith("missing_") else "whole_word_fallback"
    elif decision == "uncertain":
        if margin_source in {"missing_target_cost", "missing_competitor_cost"}:
            decision_detail = "uncertain_no_evidence"
        elif duration_fallback_triggered:
            decision_detail = "uncertain_close_call"
        else:
            decision_detail = "uncertain_margin_band"
    elif decision == "missing_score":
        decision_detail = "missing_target_score"
    else:
        decision_detail = decision

    local_evidence_summary = {
        "comparison_scope": "same_utterance_same_probe_same_acoustic_scale_only",
        "acoustic_scale": evidence.acoustic_scale,
        "raw_margin_definition": "best_competitor_cost - target_cost",
        "derived_candidate_posterior_note": "softmax(-raw_cost) within this probe only",
        "phone_alignment_available": evidence.phone_alignment_available,
        "diagnostic_phone_span_available": evidence.diagnostic_phone_span_available,
        "lattice_arc_post_available": evidence.arc_post_available,
        "duration_fallback_triggered": duration_fallback_triggered,
        "duration_decision": duration_decision,
        "margin_source": margin_source,
        "duration_source": duration_source,
        "decision_detail": decision_detail,
        "local_evidence_status": local_evidence_status,
        "local_margin_source": local_margin_source,
        "local_duration_source": local_duration_source,
        "local_score_mode": local_score_mode,
        "phone_level_evidence_status": phone_level_evidence_status,
        "local_phone_margin": local_phone_margin,
        "am_indistinguishable_pair_guard_applied": am_indistinguishable_pair_guard_applied,
    }

    return {
        "probe_graph_name": probe.get("graph_name"),
        "probe_type": probe_type,
        "target_word": target_word,
        "candidate_words": cand_words,
        "diagnostic_dimension": probe.get("diagnostic_dimension"),
        "diagnostic_dimension_hint": probe.get("diagnostic_dimension_hint")
        or probe.get("diagnostic_dimension"),
        "best_candidate": evidence.best_candidate,
        "runner_up_candidate": evidence.runner_up_candidate,
        "target_cost": target_cost,
        "target_total_cost": target_cost,
        "best_competitor_candidate": best_comp,
        "best_competitor_cost": best_comp_cost,
        "competitor_total_cost": best_comp_cost,
        "raw_margin": raw_margin,
        "whole_word_margin": whole_word_margin,
        "margin_threshold": margin_threshold,
        "small_margin_threshold": small_margin_threshold,
        "decision": decision,
        "diagnostic_label": probe_dimension_judgement(probe_type, decision),
        "target_score": target_cost,
        "score_margin": raw_margin,
        "competitor_scores": {w: probe_costs.get(w) for w in comp_words},
        "aux_normalized_score_per_frame": probe_norm,
        "derived_candidate_posterior": probe_post,
        "target_posterior": probe_post.get(target_word),
        "competitor_posteriors": {w: probe_post.get(w) for w in comp_words},
        "phone_alignment_available": evidence.phone_alignment_available,
        "diagnostic_phone_span_available": evidence.diagnostic_phone_span_available,
        "phone_alignment_summary": evidence.phone_alignment_summary,
        "arc_post_available": evidence.arc_post_available,
        "arc_post_summary": evidence.arc_post_summary,
        "target_phone_span_frames": t_frames,
        "competitor_phone_span_frames": c_frames,
        "duration_ratio": duration_ratio,
        "diagnostic_span_start": t_s,
        "diagnostic_span_end": t_e,
        "competitor_span_start": c_s,
        "competitor_span_end": c_e,
        "duration_decision": duration_decision,
        "duration_threshold": duration_threshold,
        "duration_fallback_triggered": duration_fallback_triggered,
        "margin_source": margin_source,
        "duration_source": duration_source,
        "decision_detail": decision_detail,
        "local_evidence_status": local_evidence_status,
        "local_margin_source": local_margin_source,
        "local_duration_source": local_duration_source,
        "target_vowel_frames": target_vowel_frames,
        "competitor_vowel_frames": competitor_vowel_frames,
        "target_vowel_cost": target_vowel_cost,
        "competitor_vowel_cost": competitor_vowel_cost,
        "target_vowel_acoustic_cost": target_vowel_acoustic_cost,
        "competitor_vowel_acoustic_cost": competitor_vowel_acoustic_cost,
        "target_vowel_avg_cost_per_frame": target_vowel_avg_cost_per_frame,
        "competitor_vowel_avg_cost_per_frame": competitor_vowel_avg_cost_per_frame,
        "vowel_local_margin": vowel_local_margin,
        "vowel_local_margin_phone_level": vowel_local_margin_phone_level,
        "vowel_norm_margin": vowel_norm_margin,
        "local_duration_ratio": local_duration_ratio,
        "local_duration_ratio_phone_level": local_duration_ratio_phone_level,
        "target_vowel_phone": target_vowel_phone,
        "competitor_vowel_phone": competitor_vowel_phone,
        "target_vowel_frames_phone_level": target_vowel_frames_phone_level,
        "competitor_vowel_frames_phone_level": competitor_vowel_frames_phone_level,
        "local_score_mode": local_score_mode,
        "phone_level_evidence_status": phone_level_evidence_status,
        "target_vowel_cost_source": target_vowel_cost_source,
        "competitor_vowel_cost_source": competitor_vowel_cost_source,
        "am_indistinguishable_pair_guard_applied": am_indistinguishable_pair_guard_applied,
        "local_phone_margin": local_phone_margin,
        "local_evidence_summary": local_evidence_summary,
        "notes": evidence.notes,
    }


def quantiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "min": None, "p25": None, "p50": None, "p75": None, "max": None, "mean": None}
    vs = sorted(values)

    def pick(q: float) -> float:
        idx = int(round((len(vs) - 1) * q))
        return vs[idx]

    return {
        "n": len(vs),
        "min": vs[0],
        "p25": pick(0.25),
        "p50": pick(0.50),
        "p75": pick(0.75),
        "max": vs[-1],
        "mean": sum(vs) / len(vs),
    }


def summarize_micro_results(rows: list[dict]) -> dict:
    by_probe = defaultdict(list)
    by_dim = defaultdict(list)
    confusion = Counter()

    for r in rows:
        for p in r["probes"]:
            by_probe[p["probe_type"]].append(p)
            by_dim[p["diagnostic_dimension"]].append(p)
            if p["best_candidate"] and p["best_candidate"] != p["target_word"]:
                confusion[(p["target_word"], p["best_candidate"], p["probe_type"])] += 1

    def rate(xs: list[dict], decision: str) -> float:
        if not xs:
            return 0.0
        return sum(1 for x in xs if x.get("decision") == decision) / len(xs)

    def trigger_rate(xs: list[dict]) -> float:
        if not xs:
            return 0.0
        return sum(1 for x in xs if x.get("decision") == "reject") / len(xs)

    probe_stats = {}
    for probe_type, xs in sorted(by_probe.items()):
        margins = [x["raw_margin"] for x in xs if x.get("raw_margin") is not None]
        durations = [x["duration_ratio"] for x in xs if x.get("duration_ratio") is not None]
        dur_trigger = sum(1 for x in xs if x.get("duration_fallback_triggered") is True)
        probe_stats[probe_type] = {
            "n": len(xs),
            "accept_rate": rate(xs, "accept"),
            "reject_rate": rate(xs, "reject"),
            "uncertain_rate": rate(xs, "uncertain"),
            "error_trigger_rate": trigger_rate(xs),
            "duration_fallback_trigger_rate": (dur_trigger / len(xs)) if xs else 0.0,
            "raw_margin_distribution": quantiles(margins),
            "duration_evidence_distribution": quantiles(durations),
        }

    dim_stats = {}
    for dim, xs in sorted(by_dim.items()):
        margins = [x["raw_margin"] for x in xs if x.get("raw_margin") is not None]
        durations = [x["duration_ratio"] for x in xs if x.get("duration_ratio") is not None]
        dur_trigger = sum(1 for x in xs if x.get("duration_fallback_triggered") is True)
        dim_stats[dim] = {
            "n": len(xs),
            "accept_rate": rate(xs, "accept"),
            "reject_rate": rate(xs, "reject"),
            "uncertain_rate": rate(xs, "uncertain"),
            "error_trigger_rate": trigger_rate(xs),
            "duration_fallback_trigger_rate": (dur_trigger / len(xs)) if xs else 0.0,
            "raw_margin_distribution": quantiles(margins),
            "duration_evidence_distribution": quantiles(durations),
        }

    top_confusions = [
        {"target_word": t, "best_candidate": b, "probe_type": p, "count": c}
        for (t, b, p), c in confusion.most_common(20)
    ]

    vowel_rows = by_probe.get("vowel_probe", [])
    phone_level_status_counts = dict(Counter(x.get("phone_level_evidence_status", "missing") for x in vowel_rows))
    decision_detail_counts = dict(Counter(x.get("decision_detail", "missing") for x in vowel_rows))
    guard_applied_count = sum(1 for x in vowel_rows if x.get("am_indistinguishable_pair_guard_applied") is True)
    fixed_pairs = {
        frozenset({"gop", "gope"}),
        frozenset({"vop", "vope"}),
        frozenset({"wot", "wote"}),
        frozenset({"jop", "jope"}),
    }
    fixed_pair_rows = []
    for x in vowel_rows:
        comp = x.get("best_competitor_candidate")
        if not comp:
            continue
        if frozenset({x.get("target_word"), comp}) in fixed_pairs:
            fixed_pair_rows.append(x)
    fixed_with_margin = [x for x in fixed_pair_rows if x.get("vowel_local_margin_phone_level") is not None]
    fixed_zero = [x for x in fixed_with_margin if float(x.get("vowel_local_margin_phone_level")) == 0.0]
    fixed_nonzero = [x for x in fixed_with_margin if float(x.get("vowel_local_margin_phone_level")) != 0.0]

    return {
        "probe_type_stats": probe_stats,
        "diagnostic_dimension_stats": dim_stats,
        "major_probe_confusions": top_confusions,
        "vowel_probe_phone_level_evidence_status_distribution": phone_level_status_counts,
        "vowel_probe_decision_detail_distribution": decision_detail_counts,
        "vowel_probe_am_indistinguishable_pair_guard_applied_count": guard_applied_count,
        "vowel_probe_fixed_pair_phone_level_margin_stats": {
            "fixed_pair_rows": len(fixed_pair_rows),
            "with_phone_level_margin": len(fixed_with_margin),
            "phone_level_margin_eq_0_count": len(fixed_zero),
            "phone_level_margin_ne_0_count": len(fixed_nonzero),
            "phone_level_margin_eq_0_ratio": (len(fixed_zero) / len(fixed_with_margin)) if fixed_with_margin else 0.0,
            "phone_level_margin_ne_0_ratio": (len(fixed_nonzero) / len(fixed_with_margin)) if fixed_with_margin else 0.0,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="T04_EN micro-probe scoring with probe-local raw margin as formal criterion."
    )
    ap.add_argument("--runtime-root", default="egs/t04_en_constrained/s5/runtime")
    ap.add_argument("--config-json", default="egs/t04_en_constrained/s5/config/t04_word_sets.json")
    ap.add_argument("--main-manifest", default="")
    ap.add_argument("--probe-manifest", default="")
    ap.add_argument("--wav-dir", required=True)
    ap.add_argument("--model-dir", default="")
    ap.add_argument("--margin-threshold", type=float, default=0.0)
    ap.add_argument("--small-margin-threshold", type=float, default=0.05)
    ap.add_argument("--duration-threshold", type=float, default=1.2)
    ap.add_argument("--vowel-local-margin-threshold", type=float, default=0.05)
    ap.add_argument(
        "--known-am-indistinguishable-pairs",
        default=DEFAULT_AM_INDISTINGUISHABLE_PAIRS,
        help="Comma-separated pairs like gop:gope,vop:vope; only these pairs trigger AM indistinguishable guard.",
    )
    ap.add_argument("--acoustic-scale", type=float, default=0.1)
    ap.add_argument("--nbest-n", type=int, default=10)
    ap.add_argument("--output-json", default="")
    ap.add_argument("--summary-json", default="")
    ap.add_argument("--output-csv", default="")
    args = ap.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    s5_root = runtime_root.parent
    config_json = Path(args.config_json).resolve()
    wav_dir = Path(args.wav_dir).resolve()
    model_dir = resolve_model_dir(runtime_root, args.model_dir)
    known_am_indistinguishable_pairs = parse_pair_set(args.known_am_indistinguishable_pairs)

    main_manifest = (
        Path(args.main_manifest).resolve()
        if args.main_manifest
        else runtime_root / "manifests" / "t04_graph_manifest.json"
    )
    probe_manifest = (
        Path(args.probe_manifest).resolve()
        if args.probe_manifest
        else runtime_root / "manifests" / "t04_probe_manifest.json"
    )

    out_root = runtime_root / "diagnostic"
    output_json = Path(args.output_json).resolve() if args.output_json else out_root / "t04_micro_probe_results.json"
    summary_json = Path(args.summary_json).resolve() if args.summary_json else out_root / "t04_micro_probe_summary.json"
    output_csv = Path(args.output_csv).resolve() if args.output_csv else out_root / "t04_micro_probe_results.csv"

    eval_rows = build_eval_rows(config_json)
    main_entries = {e["graph_name"]: e for e in read_json(main_manifest).get("entries", [])}
    probe_entries = read_json(probe_manifest).get("entries", [])
    probes_by_target = defaultdict(list)
    for p in probe_entries:
        probes_by_target[(p.get("parent_level_graph"), p.get("target_word"))].append(p)

    rows = []
    flat_rows = []

    for row in eval_rows:
        utt_id = row["utt_id"]
        target = row["target_word"]
        parent_level = row["parent_level_graph"]
        wav_path = wav_dir / f"{utt_id}.wav"

        probe_results = []
        for probe in probes_by_target.get((parent_level, target), []):
            graph_path = probe.get("graph_path") or main_entries.get(probe["graph_name"], {}).get("graph_dir")
            lang_graph_path = probe.get("lang_graph_path") or str(runtime_root / "lang_graphs" / probe["graph_name"])
            graph_dir = Path(graph_path).resolve() if graph_path else Path("/nonexistent")
            words_txt = Path(lang_graph_path).resolve() / "words.txt"

            evidence = run_decode_constrained(
                wav_path=wav_path,
                graph_dir=graph_dir,
                words_txt=words_txt,
                model_dir=model_dir,
                s5_root=s5_root,
                nbest_n=max(args.nbest_n, len(probe.get("candidate_words", [])) + 2),
                acoustic_scale=args.acoustic_scale,
            )
            local_vowel_evidence = None
            if (probe.get("probe_type") or "") == "vowel_probe":
                cand_words = probe.get("candidate_words", [])
                local_comp = next((w for w in cand_words if w != target), None)
                local_vowel_evidence = build_vowel_local_evidence(
                    runtime_root=runtime_root,
                    s5_root=s5_root,
                    model_dir=model_dir,
                    wav_path=wav_path,
                    target_word=target,
                    competitor_word=local_comp,
                    probe_evidence=evidence,
                    acoustic_scale=args.acoustic_scale,
                )
            scored = score_one_probe(
                target,
                probe,
                evidence,
                args.margin_threshold,
                args.small_margin_threshold,
                args.duration_threshold,
                local_vowel_evidence=local_vowel_evidence,
                vowel_local_margin_threshold=args.vowel_local_margin_threshold,
                known_am_indistinguishable_pairs=known_am_indistinguishable_pairs,
            )
            probe_results.append(scored)

            flat_rows.append(
                {
                    "utt_id": utt_id,
                    "target_word": target,
                    "source_set": row["source_set"],
                    "parent_level_graph": parent_level,
                    "probe_type": scored["probe_type"],
                    "diagnostic_dimension": scored["diagnostic_dimension"],
                    "best_candidate": scored["best_candidate"] or "",
                    "runner_up_candidate": scored["runner_up_candidate"] or "",
                    "target_cost": "" if scored["target_cost"] is None else f"{scored['target_cost']:.6f}",
                    "target_total_cost": "" if scored["target_total_cost"] is None else f"{scored['target_total_cost']:.6f}",
                    "best_competitor_cost": ""
                    if scored["best_competitor_cost"] is None
                    else f"{scored['best_competitor_cost']:.6f}",
                    "competitor_total_cost": ""
                    if scored["competitor_total_cost"] is None
                    else f"{scored['competitor_total_cost']:.6f}",
                    "best_competitor_candidate": scored["best_competitor_candidate"] or "",
                    "raw_margin": "" if scored["raw_margin"] is None else f"{scored['raw_margin']:.6f}",
                    "whole_word_margin": "" if scored["whole_word_margin"] is None else f"{scored['whole_word_margin']:.6f}",
                    "margin_threshold": f"{scored['margin_threshold']:.6f}",
                    "duration_ratio": "" if scored["duration_ratio"] is None else f"{scored['duration_ratio']:.6f}",
                    "target_phone_span_frames": scored["target_phone_span_frames"],
                    "competitor_phone_span_frames": scored["competitor_phone_span_frames"],
                    "target_vowel_phone": scored["target_vowel_phone"] or "",
                    "competitor_vowel_phone": scored["competitor_vowel_phone"] or "",
                    "target_vowel_frames": scored["target_vowel_frames"],
                    "competitor_vowel_frames": scored["competitor_vowel_frames"],
                    "target_vowel_frames_phone_level": scored["target_vowel_frames_phone_level"],
                    "competitor_vowel_frames_phone_level": scored["competitor_vowel_frames_phone_level"],
                    "target_vowel_cost": ""
                    if scored["target_vowel_cost"] is None
                    else f"{scored['target_vowel_cost']:.6f}",
                    "competitor_vowel_cost": ""
                    if scored["competitor_vowel_cost"] is None
                    else f"{scored['competitor_vowel_cost']:.6f}",
                    "target_vowel_acoustic_cost": ""
                    if scored["target_vowel_acoustic_cost"] is None
                    else f"{scored['target_vowel_acoustic_cost']:.6f}",
                    "competitor_vowel_acoustic_cost": ""
                    if scored["competitor_vowel_acoustic_cost"] is None
                    else f"{scored['competitor_vowel_acoustic_cost']:.6f}",
                    "target_vowel_avg_cost_per_frame": ""
                    if scored["target_vowel_avg_cost_per_frame"] is None
                    else f"{scored['target_vowel_avg_cost_per_frame']:.6f}",
                    "competitor_vowel_avg_cost_per_frame": ""
                    if scored["competitor_vowel_avg_cost_per_frame"] is None
                    else f"{scored['competitor_vowel_avg_cost_per_frame']:.6f}",
                    "vowel_local_margin": ""
                    if scored["vowel_local_margin"] is None
                    else f"{scored['vowel_local_margin']:.6f}",
                    "vowel_local_margin_phone_level": ""
                    if scored["vowel_local_margin_phone_level"] is None
                    else f"{scored['vowel_local_margin_phone_level']:.6f}",
                    "vowel_norm_margin": ""
                    if scored["vowel_norm_margin"] is None
                    else f"{scored['vowel_norm_margin']:.6f}",
                    "local_duration_ratio": ""
                    if scored["local_duration_ratio"] is None
                    else f"{scored['local_duration_ratio']:.6f}",
                    "local_duration_ratio_phone_level": ""
                    if scored["local_duration_ratio_phone_level"] is None
                    else f"{scored['local_duration_ratio_phone_level']:.6f}",
                    "local_phone_margin": ""
                    if scored["local_phone_margin"] is None
                    else f"{scored['local_phone_margin']:.6f}",
                    "duration_decision": scored["duration_decision"],
                    "duration_fallback_triggered": scored["duration_fallback_triggered"],
                    "margin_source": scored["margin_source"],
                    "duration_source": scored["duration_source"],
                    "decision_detail": scored["decision_detail"],
                    "local_evidence_status": scored["local_evidence_status"],
                    "local_margin_source": scored["local_margin_source"],
                    "local_duration_source": scored["local_duration_source"],
                    "local_score_mode": scored["local_score_mode"],
                    "phone_level_evidence_status": scored["phone_level_evidence_status"],
                    "target_vowel_cost_source": scored["target_vowel_cost_source"] or "",
                    "competitor_vowel_cost_source": scored["competitor_vowel_cost_source"] or "",
                    "am_indistinguishable_pair_guard_applied": scored["am_indistinguishable_pair_guard_applied"],
                    "decision": scored["decision"],
                    "diagnostic_label": scored["diagnostic_label"],
                    "phone_alignment_available": scored["phone_alignment_available"],
                    "diagnostic_phone_span_available": scored["diagnostic_phone_span_available"],
                    "probe_graph_name": scored["probe_graph_name"],
                }
            )

        auxiliary = []
        for mode_name, suffix in WHOLE_WORD_AUX_SUFFIX.items():
            graph_name = f"T04_ITEM_{parent_level}_{target}_{suffix}"
            entry = main_entries.get(graph_name)
            if not entry:
                auxiliary.append(
                    {"mode": mode_name, "graph_name": graph_name, "available": False, "notes": ["missing_graph_in_manifest"]}
                )
                continue

            evidence = run_decode_constrained(
                wav_path=wav_path,
                graph_dir=Path(entry.get("graph_dir") or "/nonexistent").resolve(),
                words_txt=Path(entry["lang_dir"]).resolve() / "words.txt",
                model_dir=model_dir,
                s5_root=s5_root,
                nbest_n=args.nbest_n,
                acoustic_scale=args.acoustic_scale,
            )
            auxiliary.append(
                {
                    "mode": mode_name,
                    "graph_name": graph_name,
                    "available": True,
                    "candidate_policy": entry.get("candidate_policy"),
                    "best_candidate": evidence.best_candidate,
                    "runner_up_candidate": evidence.runner_up_candidate,
                    "candidate_raw_costs": evidence.candidate_raw_costs,
                    "candidate_norm_scores_aux": evidence.candidate_norm_scores,
                    "candidate_posteriors_derived": evidence.candidate_posteriors,
                    "phone_alignment_available": evidence.phone_alignment_available,
                    "diagnostic_phone_span_available": evidence.diagnostic_phone_span_available,
                    "arc_post_available": evidence.arc_post_available,
                    "notes": evidence.notes,
                }
            )

        rows.append(
            {
                "utt_id": utt_id,
                "wav_path": str(wav_path),
                "target_word": target,
                "level": row["level"],
                "source_set": row["source_set"],
                "parent_level_graph": parent_level,
                "formal_probe_results": probe_results,
                "probes": probe_results,
                "auxiliary_whole_word_results": auxiliary,
            }
        )

    summary = summarize_micro_results(rows)
    summary["margin_threshold"] = args.margin_threshold
    summary["small_margin_threshold"] = args.small_margin_threshold
    summary["duration_threshold"] = args.duration_threshold
    summary["vowel_local_margin_threshold"] = args.vowel_local_margin_threshold
    summary["known_am_indistinguishable_pairs"] = sorted(
        ["/".join(sorted(list(p))) for p in known_am_indistinguishable_pairs]
    )
    summary["margin_definition"] = "raw_margin = best_competitor_cost - target_cost"
    summary["formal_decision_criterion"] = "probe_local_raw_margin"
    summary["score_scope_constraints"] = [
        "same utterance",
        "same probe graph",
        "same acoustic scale",
        "no cross-probe raw margin comparison",
    ]
    summary["auxiliary_modes"] = list(WHOLE_WORD_AUX_SUFFIX.keys())

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            {
                "task_id": "T04_EN",
                "formal_diagnostic_default": "candidate_specific_micro_probe_raw_margin",
                "results": rows,
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    summary_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    for probe_type, stats in summary.get("probe_type_stats", {}).items():
        one_path = summary_json.parent / f"t04_micro_probe_summary_{probe_type}.json"
        one_path.write_text(
            json.dumps(
                {
                    "probe_type": probe_type,
                    "stats": stats,
                    "margin_threshold": args.margin_threshold,
                    "small_margin_threshold": args.small_margin_threshold,
                    "duration_threshold": args.duration_threshold,
                },
                ensure_ascii=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "utt_id",
                "target_word",
                "source_set",
                "parent_level_graph",
                "probe_type",
                "diagnostic_dimension",
                "best_candidate",
                "runner_up_candidate",
                "target_cost",
                "target_total_cost",
                "best_competitor_cost",
                "competitor_total_cost",
                "best_competitor_candidate",
                "raw_margin",
                "whole_word_margin",
                "margin_threshold",
                "duration_ratio",
                "target_phone_span_frames",
                "competitor_phone_span_frames",
                "target_vowel_phone",
                "competitor_vowel_phone",
                "target_vowel_frames",
                "competitor_vowel_frames",
                "target_vowel_frames_phone_level",
                "competitor_vowel_frames_phone_level",
                "target_vowel_cost",
                "competitor_vowel_cost",
                "target_vowel_acoustic_cost",
                "competitor_vowel_acoustic_cost",
                "target_vowel_avg_cost_per_frame",
                "competitor_vowel_avg_cost_per_frame",
                "vowel_local_margin",
                "vowel_local_margin_phone_level",
                "vowel_norm_margin",
                "local_duration_ratio",
                "local_duration_ratio_phone_level",
                "local_phone_margin",
                "duration_decision",
                "duration_fallback_triggered",
                "margin_source",
                "duration_source",
                "decision_detail",
                "local_evidence_status",
                "local_margin_source",
                "local_duration_source",
                "local_score_mode",
                "phone_level_evidence_status",
                "target_vowel_cost_source",
                "competitor_vowel_cost_source",
                "am_indistinguishable_pair_guard_applied",
                "decision",
                "diagnostic_label",
                "phone_alignment_available",
                "diagnostic_phone_span_available",
                "probe_graph_name",
            ],
        )
        writer.writeheader()
        for r in flat_rows:
            writer.writerow(r)

    print(f"wrote micro-probe results: {output_json}")
    print(f"wrote micro-probe summary: {summary_json}")
    print(f"wrote micro-probe csv: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
