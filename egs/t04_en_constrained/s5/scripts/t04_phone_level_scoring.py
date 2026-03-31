#!/usr/bin/env python3

import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

VOWEL_PHONE_SET = {"O_SHORT_I", "O_LONG_I"}


@dataclass
class SharedAcousticArtifacts:
    utt_id: str
    feats_ark: Path
    ivectors_ark: Path


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


def _load_sym_word2id(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            out[cols[0]] = cols[1]
    return out


def _load_sym_id2phone(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            out[cols[1]] = cols[0]
    return out


def _load_align_lexicon(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 3:
            out[cols[1]] = cols[2:]
    return out


def _parse_int_vector_text(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 2:
            out[cols[0]] = cols[1:]
    return out


def _parse_float_vector_ark_text(path: Path) -> dict[str, list[float]]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not text.strip():
        return {}

    toks = text.replace("\n", " ").split()
    out: dict[str, list[float]] = {}
    i = 0
    while i < len(toks):
        key = toks[i]
        i += 1
        while i < len(toks) and toks[i] != "[":
            i += 1
        if i >= len(toks):
            break
        i += 1
        vals: list[float] = []
        while i < len(toks) and toks[i] != "]":
            try:
                vals.append(float(toks[i]))
            except Exception:
                pass
            i += 1
        if i < len(toks) and toks[i] == "]":
            i += 1
        out[key] = vals
    return out


def _best_contiguous_span(phone_seq: list[str], phone: str) -> tuple[int | None, int | None, int]:
    best_s = None
    best_e = None
    best_len = 0
    i = 0
    while i < len(phone_seq):
        if phone_seq[i] != phone:
            i += 1
            continue
        j = i
        while j + 1 < len(phone_seq) and phone_seq[j + 1] == phone:
            j += 1
        span_len = j - i + 1
        if span_len > best_len:
            best_s, best_e, best_len = i, j, span_len
        i = j + 1
    return best_s, best_e, best_len


def prepare_shared_acoustic_artifacts(
    *,
    s5_root: Path,
    wav_path: Path,
    model_dir: Path,
    work_dir: Path,
    utt_id: str = "utt1",
) -> tuple[SharedAcousticArtifacts | None, list[str]]:
    notes: list[str] = []
    mfcc_conf = model_dir / "conf" / "mfcc.conf"
    ivector_conf = model_dir / "conf" / "ivector_extractor.conf"
    required = [
        (wav_path, "missing_wav"),
        (model_dir / "final.mdl", "missing_final_mdl"),
        (mfcc_conf, "missing_mfcc_conf"),
        (ivector_conf, "missing_ivector_extractor_conf"),
    ]
    for path, tag in required:
        if not path.exists():
            notes.append(tag)
    if notes:
        return None, notes

    spk2utt = work_dir / "spk2utt"
    wav_scp = work_dir / "wav.scp"
    feats_ark = work_dir / "feats.ark"
    ivectors_ark = work_dir / "ivectors.ark"

    spk2utt.write_text(f"{utt_id} {utt_id}\n", encoding="utf-8")
    wav_scp.write_text(f"{utt_id} {wav_path}\n", encoding="utf-8")

    mfcc_sh = (
        f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
        f"compute-mfcc-feats --config={shlex.quote(str(mfcc_conf))} "
        f"scp:{shlex.quote(str(wav_scp))} ark:{shlex.quote(str(feats_ark))}"
    )
    ok, _ = run_kaldi_cmd(mfcc_sh)
    if not ok:
        return None, ["compute_mfcc_failed"]

    ivec_sh = (
        f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
        f"ivector-extract-online2 --config={shlex.quote(str(ivector_conf))} --repeat=true "
        f"ark:{shlex.quote(str(spk2utt))} ark:{shlex.quote(str(feats_ark))} ark:{shlex.quote(str(ivectors_ark))}"
    )
    ok, _ = run_kaldi_cmd(ivec_sh)
    if not ok:
        return None, ["ivector_extract_failed"]

    return SharedAcousticArtifacts(utt_id=utt_id, feats_ark=feats_ark, ivectors_ark=ivectors_ark), notes


def force_align_single_pronunciation(
    *,
    runtime_root: Path,
    s5_root: Path,
    model_dir: Path,
    word: str,
    acoustic_scale: float,
    shared_artifacts: SharedAcousticArtifacts,
    work_dir: Path,
) -> dict:
    lang_dir = runtime_root / "lang" / "lang_t04"
    words_txt = lang_dir / "words.txt"
    phones_txt = lang_dir / "phones.txt"
    align_lexicon_txt = lang_dir / "phones" / "align_lexicon.txt"
    l_fst = lang_dir / "L.fst"
    final_mdl = model_dir / "final.mdl"
    tree = model_dir / "tree"

    required = [
        (words_txt, "missing_words_txt"),
        (phones_txt, "missing_phones_txt"),
        (align_lexicon_txt, "missing_align_lexicon"),
        (l_fst, "missing_l_fst"),
        (final_mdl, "missing_final_mdl"),
        (tree, "missing_tree"),
    ]
    missing = [tag for p, tag in required if not p.exists()]
    if missing:
        return {
            "status": "missing_resources",
            "word": word,
            "notes": missing,
            "cost_source": "unavailable_missing_resources",
            "vowel_phone": None,
            "vowel_frames": None,
            "vowel_acoustic_cost": None,
            "vowel_avg_cost_per_frame": None,
        }

    word2id = _load_sym_word2id(words_txt)
    id2phone = _load_sym_id2phone(phones_txt)
    lex = _load_align_lexicon(align_lexicon_txt)
    pron = lex.get(word)
    if not pron:
        return {
            "status": "missing_pronunciation",
            "word": word,
            "notes": ["missing_pronunciation"],
            "cost_source": "unavailable_missing_pronunciation",
            "vowel_phone": None,
            "vowel_frames": None,
            "vowel_acoustic_cost": None,
            "vowel_avg_cost_per_frame": None,
        }

    vowel_phone = next((p for p in pron if p in VOWEL_PHONE_SET), None)
    if vowel_phone is None:
        return {
            "status": "no_vowel_phone_in_pronunciation",
            "word": word,
            "notes": ["no_vowel_phone_in_pronunciation"],
            "cost_source": "unavailable_no_vowel_phone",
            "vowel_phone": None,
            "vowel_frames": None,
            "vowel_acoustic_cost": None,
            "vowel_avg_cost_per_frame": None,
        }

    word_id = word2id.get(word)
    if word_id is None:
        return {
            "status": "missing_word_symbol",
            "word": word,
            "notes": ["missing_word_symbol"],
            "cost_source": "unavailable_missing_word_symbol",
            "vowel_phone": vowel_phone,
            "vowel_frames": None,
            "vowel_acoustic_cost": None,
            "vowel_avg_cost_per_frame": None,
        }

    text_int = work_dir / f"{word}.text.int"
    graphs_ark = work_dir / f"{word}.graphs.ark"
    ali_ark = work_dir / f"{word}.ali.ark"
    ali_phone_txt = work_dir / f"{word}.ali_phone.txt"
    like_txt = work_dir / f"{word}.per_frame_like.txt"

    text_int.write_text(f"{shared_artifacts.utt_id} {word_id}\n", encoding="utf-8")

    graph_sh = (
        f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
        f"compile-train-graphs {shlex.quote(str(tree))} {shlex.quote(str(final_mdl))} {shlex.quote(str(l_fst))} "
        f"ark,t:{shlex.quote(str(text_int))} ark:{shlex.quote(str(graphs_ark))}"
    )
    ok, _ = run_kaldi_cmd(graph_sh)
    if not ok:
        return {
            "status": "compile_graph_failed",
            "word": word,
            "notes": ["compile_graph_failed"],
            "cost_source": "unavailable_compile_graph_failed",
            "vowel_phone": vowel_phone,
            "vowel_frames": None,
            "vowel_acoustic_cost": None,
            "vowel_avg_cost_per_frame": None,
        }

    align_sh = (
        f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
        f"nnet3-align-compiled --acoustic-scale={acoustic_scale} --beam=200 --retry-beam=0 "
        f"--online-ivectors=ark:{shlex.quote(str(shared_artifacts.ivectors_ark))} --online-ivector-period=1 "
        f"--write-per-frame-acoustic-loglikes=ark,t:{shlex.quote(str(like_txt))} "
        f"{shlex.quote(str(final_mdl))} ark:{shlex.quote(str(graphs_ark))} "
        f"ark:{shlex.quote(str(shared_artifacts.feats_ark))} ark:{shlex.quote(str(ali_ark))}"
    )
    ok, _ = run_kaldi_cmd(align_sh)
    if not ok:
        return {
            "status": "no_alignment",
            "word": word,
            "notes": ["nnet3_align_failed"],
            "cost_source": "unavailable_no_alignment",
            "vowel_phone": vowel_phone,
            "vowel_frames": None,
            "vowel_acoustic_cost": None,
            "vowel_avg_cost_per_frame": None,
        }

    ali_phone_sh = (
        f"set -euo pipefail; . {shlex.quote(str(s5_root / 'path.sh'))}; "
        f"ali-to-phones --per-frame=true {shlex.quote(str(final_mdl))} "
        f"ark:{shlex.quote(str(ali_ark))} ark,t:{shlex.quote(str(ali_phone_txt))}"
    )
    ok, _ = run_kaldi_cmd(ali_phone_sh)
    if not ok:
        return {
            "status": "no_alignment",
            "word": word,
            "notes": ["ali_to_phones_failed"],
            "cost_source": "unavailable_no_alignment",
            "vowel_phone": vowel_phone,
            "vowel_frames": None,
            "vowel_acoustic_cost": None,
            "vowel_avg_cost_per_frame": None,
        }

    phone_id_seq = _parse_int_vector_text(ali_phone_txt).get(shared_artifacts.utt_id, [])
    phone_seq = [id2phone.get(pid, pid) for pid in phone_id_seq]
    frame_likes = _parse_float_vector_ark_text(like_txt).get(shared_artifacts.utt_id, [])
    if not phone_seq or not frame_likes:
        return {
            "status": "score_unavailable",
            "word": word,
            "notes": ["missing_phone_seq_or_likelihoods"],
            "cost_source": "unavailable_score_unavailable",
            "vowel_phone": vowel_phone,
            "vowel_frames": None,
            "vowel_acoustic_cost": None,
            "vowel_avg_cost_per_frame": None,
        }

    n = min(len(phone_seq), len(frame_likes))
    phone_seq = phone_seq[:n]
    frame_likes = frame_likes[:n]

    s, e, span_len = _best_contiguous_span(phone_seq, vowel_phone)
    if span_len <= 0 or s is None or e is None:
        return {
            "status": "no_vowel_span",
            "word": word,
            "notes": ["no_vowel_span"],
            "cost_source": "unavailable_no_vowel_span",
            "vowel_phone": vowel_phone,
            "vowel_frames": 0,
            "vowel_acoustic_cost": None,
            "vowel_avg_cost_per_frame": None,
        }

    vowel_likes = frame_likes[s : e + 1]
    # Convert log-likelihood to cost so lower is better and margins stay competitor-target.
    vowel_cost = -sum(vowel_likes)
    return {
        "status": "ok",
        "word": word,
        "notes": [],
        "cost_source": "phone_level_forced_align",
        "vowel_phone": vowel_phone,
        "vowel_frame_start": s,
        "vowel_frame_end": e,
        "vowel_frames": span_len,
        "vowel_acoustic_cost": vowel_cost,
        "vowel_avg_cost_per_frame": (vowel_cost / span_len) if span_len > 0 else None,
        "alignment_total_frames": n,
    }


def score_vowel_pair_phone_level(
    *,
    runtime_root: Path,
    s5_root: Path,
    model_dir: Path,
    wav_path: Path,
    target_word: str,
    competitor_word: str,
    acoustic_scale: float,
) -> dict:
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        shared, prep_notes = prepare_shared_acoustic_artifacts(
            s5_root=s5_root,
            wav_path=wav_path,
            model_dir=model_dir,
            work_dir=work_dir,
        )
        if shared is None:
            return {
                "status": "shared_feature_prepare_failed",
                "local_score_mode": "forced_align_phone_level",
                "phone_level_evidence_status": "shared_feature_prepare_failed",
                "notes": prep_notes,
                "target": {
                    "status": "shared_feature_prepare_failed",
                    "word": target_word,
                    "vowel_phone": None,
                    "vowel_frames": None,
                    "vowel_acoustic_cost": None,
                    "vowel_avg_cost_per_frame": None,
                    "cost_source": "unavailable_shared_feature_prepare_failed",
                },
                "competitor": {
                    "status": "shared_feature_prepare_failed",
                    "word": competitor_word,
                    "vowel_phone": None,
                    "vowel_frames": None,
                    "vowel_acoustic_cost": None,
                    "vowel_avg_cost_per_frame": None,
                    "cost_source": "unavailable_shared_feature_prepare_failed",
                },
                "vowel_local_margin_phone_level": None,
                "local_duration_ratio_phone_level": None,
            }

        target = force_align_single_pronunciation(
            runtime_root=runtime_root,
            s5_root=s5_root,
            model_dir=model_dir,
            word=target_word,
            acoustic_scale=acoustic_scale,
            shared_artifacts=shared,
            work_dir=work_dir,
        )
        competitor = force_align_single_pronunciation(
            runtime_root=runtime_root,
            s5_root=s5_root,
            model_dir=model_dir,
            word=competitor_word,
            acoustic_scale=acoustic_scale,
            shared_artifacts=shared,
            work_dir=work_dir,
        )

    pair_status = "ok" if target.get("status") == "ok" and competitor.get("status") == "ok" else "unavailable"

    margin = None
    duration_ratio = None
    if pair_status == "ok":
        t_cost = target.get("vowel_acoustic_cost")
        c_cost = competitor.get("vowel_acoustic_cost")
        if t_cost is not None and c_cost is not None:
            margin = c_cost - t_cost
        t_frames = target.get("vowel_frames")
        c_frames = competitor.get("vowel_frames")
        if t_frames and c_frames:
            duration_ratio = t_frames / float(c_frames)

    return {
        "status": pair_status,
        "local_score_mode": "forced_align_phone_level",
        "phone_level_evidence_status": "ok" if pair_status == "ok" else "unavailable",
        "notes": prep_notes,
        "target": target,
        "competitor": competitor,
        "vowel_local_margin_phone_level": margin,
        "local_duration_ratio_phone_level": duration_ratio,
    }
