#!/usr/bin/env python3

import argparse
import csv
import subprocess
import tempfile
from pathlib import Path


def must_have_cmd(name: str) -> None:
    r = subprocess.run(["bash", "-lc", f"command -v {name}"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"required command not found: {name}")


def load_ipa_map(path: Path) -> dict[str, str]:
    m = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            w = (row.get("word") or "").strip().lower()
            ipa = (row.get("espeak_ipa") or "").strip()
            if w and ipa:
                m[w] = ipa
    if not m:
        raise RuntimeError(f"no ipa mapping loaded from {path}")
    return m


def load_eval_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise RuntimeError(f"empty eval csv: {path}")
    for c in ["utt_id", "target_word"]:
        if c not in rows[0]:
            raise RuntimeError(f"missing required column '{c}' in {path}")
    return rows


def synth_one(ipa_text: str, wav_path: Path, voice: str, speed: int, pitch: int, volume: int) -> None:
    with tempfile.TemporaryDirectory() as td:
        raw_wav = Path(td) / "raw.wav"
        cmd = [
            "espeak-ng",
            "-v",
            voice,
            "-s",
            str(speed),
            "-p",
            str(pitch),
            "-a",
            str(volume),
            "-w",
            str(raw_wav),
            ipa_text,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"espeak-ng failed: {p.stderr.strip()}")

        wav_path.parent.mkdir(parents=True, exist_ok=True)
        p2 = subprocess.run(
            ["sox", str(raw_wav), "-r", "16000", "-c", "1", str(wav_path)],
            capture_output=True,
            text=True,
        )
        if p2.returncode != 0:
            raise RuntimeError(f"sox convert failed: {p2.stderr.strip()}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate 16k mono wavs from IPA map via espeak-ng")
    ap.add_argument("--eval-csv", required=True)
    ap.add_argument("--ipa-csv", default="egs/t04_en_constrained/s5/config/t04_ipa_pron_map.csv")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--voice", default="en")
    ap.add_argument("--speed", type=int, default=130)
    ap.add_argument("--pitch", type=int, default=50)
    ap.add_argument("--volume", type=int, default=120)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    must_have_cmd("espeak-ng")
    must_have_cmd("sox")

    eval_rows = load_eval_rows(Path(args.eval_csv).resolve())
    ipa_map = load_ipa_map(Path(args.ipa_csv).resolve())
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    missing = sorted({r["target_word"].strip().lower() for r in eval_rows if r["target_word"].strip().lower() not in ipa_map})
    if missing:
        raise RuntimeError(f"missing IPA mappings for target words: {missing}")

    done = 0
    for r in eval_rows:
        utt_id = r["utt_id"].strip()
        word = r["target_word"].strip().lower()
        out_wav = out_dir / f"{utt_id}.wav"
        if out_wav.exists() and not args.overwrite:
            continue
        synth_one(
            ipa_text=ipa_map[word],
            wav_path=out_wav,
            voice=args.voice,
            speed=args.speed,
            pitch=args.pitch,
            volume=args.volume,
        )
        done += 1
        print(f"generated: {out_wav.name} <= {word} {ipa_map[word]}")

    print(f"done, generated={done}, output_dir={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
