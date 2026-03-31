#!/usr/bin/env python3

import argparse
from pathlib import Path

from t04_phone_level_scoring import score_vowel_pair_phone_level


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


def fmt(v: float | int | str | None) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6f}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description="Debug T04 vowel phone-level scoring on a single wav/pair.")
    ap.add_argument("--runtime-root", default="egs/t04_en_constrained/s5/runtime")
    ap.add_argument("--wav-path", required=True)
    ap.add_argument("--target-word", required=True)
    ap.add_argument("--competitor-word", required=True)
    ap.add_argument("--model-dir", default="")
    ap.add_argument("--acoustic-scale", type=float, default=0.1)
    args = ap.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    s5_root = runtime_root.parent
    model_dir = resolve_model_dir(runtime_root, args.model_dir)

    pair = score_vowel_pair_phone_level(
        runtime_root=runtime_root,
        s5_root=s5_root,
        model_dir=model_dir,
        wav_path=Path(args.wav_path).resolve(),
        target_word=args.target_word,
        competitor_word=args.competitor_word,
        acoustic_scale=args.acoustic_scale,
    )

    t = pair.get("target", {})
    c = pair.get("competitor", {})
    print(f"target_word={args.target_word}")
    print(f"competitor_word={args.competitor_word}")
    print(f"phone_level_evidence_status={pair.get('phone_level_evidence_status')}")
    print(f"local_score_mode={pair.get('local_score_mode')}")
    print(f"target_status={t.get('status')}")
    print(f"competitor_status={c.get('status')}")
    print(f"target_vowel_phone={t.get('vowel_phone')}")
    print(f"competitor_vowel_phone={c.get('vowel_phone')}")
    print(f"target_vowel_frames={fmt(t.get('vowel_frames'))}")
    print(f"competitor_vowel_frames={fmt(c.get('vowel_frames'))}")
    print(f"target_vowel_acoustic_cost={fmt(t.get('vowel_acoustic_cost'))}")
    print(f"competitor_vowel_acoustic_cost={fmt(c.get('vowel_acoustic_cost'))}")
    print(f"target_vowel_avg_cost_per_frame={fmt(t.get('vowel_avg_cost_per_frame'))}")
    print(f"competitor_vowel_avg_cost_per_frame={fmt(c.get('vowel_avg_cost_per_frame'))}")
    print(f"vowel_local_margin={fmt(pair.get('vowel_local_margin_phone_level'))}")
    print(f"local_duration_ratio_phone_level={fmt(pair.get('local_duration_ratio_phone_level'))}")
    if pair.get("notes"):
        print(f"notes={pair.get('notes')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
