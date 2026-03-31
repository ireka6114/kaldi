#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

WAV_RE = re.compile(r"^(cvc|cvce)_([a-z]+)_r([0-9]+)\.wav$")


def parse_pair(p: str) -> tuple[str, str] | None:
    if ":" in p:
        a, b = p.split(":", 1)
    elif "/" in p:
        a, b = p.split("/", 1)
    else:
        return None
    a = a.strip()
    b = b.strip()
    if not a or not b or a == b:
        return None
    return a, b


def load_conf(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_wav_inventory(wav_dir: Path) -> dict[tuple[str, int], Path]:
    inv: dict[tuple[str, int], Path] = {}
    for wav in sorted(wav_dir.glob("*.wav")):
        m = WAV_RE.match(wav.name)
        if not m:
            continue
        _level, word, rep_s = m.groups()
        inv[(word, int(rep_s))] = wav.resolve()
    return inv


def to_word_sets(eval_words: set[str]) -> dict:
    cvc = sorted([w for w in eval_words if not w.endswith("e")])
    cvce = sorted([w for w in eval_words if w.endswith("e")])
    return {
        "formal_levels": {
            "T04_CVC": {"level_tag": "T04_CVC", "source_set": "CVC", "words": cvc},
            "T04_CVCE": {"level_tag": "T04_CVCE", "source_set": "CVCE", "words": cvce},
            "T04_ING_A": {"level_tag": "T04_ING_A", "source_set": "ING_A", "words": []},
            "T04_ING_B": {"level_tag": "T04_ING_B", "source_set": "ING_B", "words": []},
        }
    }


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=True) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate focused manifests for T04 minimal-pair AM experiment.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    conf_path = Path(args.config).resolve()
    out_dir = Path(args.output_dir).resolve()
    conf = load_conf(conf_path)

    train_wav_dir = Path(conf["train_wav_dir"]).resolve()
    eval_wav_dir = Path(conf["eval_wav_dir"]).resolve()
    fixed_pairs = [p for p in (parse_pair(x) for x in conf.get("fixed_pairs", [])) if p]
    control_pairs = [p for p in (parse_pair(x) for x in conf.get("control_pairs", [])) if p]
    include_controls_in_train = bool(conf.get("include_control_pairs_in_train", True))

    train_reps = set(int(x) for x in conf.get("train_reps", [1]))
    dev_reps = set(int(x) for x in conf.get("dev_reps", [2]))
    eval_reps = set(int(x) for x in conf.get("eval_reps", [1, 2]))

    train_inv = parse_wav_inventory(train_wav_dir)
    eval_inv = parse_wav_inventory(eval_wav_dir)

    train_pairs = list(fixed_pairs)
    if include_controls_in_train:
        train_pairs.extend(control_pairs)

    train_rows: list[dict] = []
    dev_rows: list[dict] = []
    eval_rows: list[dict] = []
    eval_words: set[str] = set()

    for group_name, pairs in (("fixed", fixed_pairs), ("control", control_pairs)):
        for a, b in pairs:
            for word, role in ((a, "target"), (b, "competitor")):
                for rep in sorted(eval_reps):
                    wav = eval_inv.get((word, rep))
                    if wav is None:
                        continue
                    eval_rows.append(
                        {
                            "group": group_name,
                            "pair": f"{a}:{b}",
                            "word": word,
                            "role": role,
                            "rep": rep,
                            "split": "eval",
                            "wav_path": str(wav),
                            "utt_id": wav.stem,
                        }
                    )
                    eval_words.add(word)

    for a, b in train_pairs:
        for word, role in ((a, "target"), (b, "competitor")):
            for rep in sorted(train_reps):
                wav = train_inv.get((word, rep))
                if wav is None:
                    continue
                train_rows.append(
                    {
                        "group": "fixed" if (a, b) in fixed_pairs else "control",
                        "pair": f"{a}:{b}",
                        "word": word,
                        "role": role,
                        "rep": rep,
                        "split": "train",
                        "wav_path": str(wav),
                        "utt_id": wav.stem,
                    }
                )
            for rep in sorted(dev_reps):
                wav = train_inv.get((word, rep))
                if wav is None:
                    continue
                dev_rows.append(
                    {
                        "group": "fixed" if (a, b) in fixed_pairs else "control",
                        "pair": f"{a}:{b}",
                        "word": word,
                        "role": role,
                        "rep": rep,
                        "split": "dev",
                        "wav_path": str(wav),
                        "utt_id": wav.stem,
                    }
                )

    write_jsonl(out_dir / "minpair_train_manifest.jsonl", train_rows)
    write_jsonl(out_dir / "minpair_dev_manifest.jsonl", dev_rows)
    write_jsonl(out_dir / "minpair_eval_manifest.jsonl", eval_rows)
    write_json(out_dir / "minpair_eval_word_sets.json", to_word_sets(eval_words))
    write_json(
        out_dir / "minpair_manifest_summary.json",
        {
            "config_path": str(conf_path),
            "train_wav_dir": str(train_wav_dir),
            "eval_wav_dir": str(eval_wav_dir),
            "fixed_pairs": [f"{a}:{b}" for a, b in fixed_pairs],
            "control_pairs": [f"{a}:{b}" for a, b in control_pairs],
            "train_rows": len(train_rows),
            "dev_rows": len(dev_rows),
            "eval_rows": len(eval_rows),
            "train_reps": sorted(train_reps),
            "dev_reps": sorted(dev_reps),
            "eval_reps": sorted(eval_reps),
        },
    )

    print(f"wrote train manifest: {out_dir / 'minpair_train_manifest.jsonl'}")
    print(f"wrote dev manifest: {out_dir / 'minpair_dev_manifest.jsonl'}")
    print(f"wrote eval manifest: {out_dir / 'minpair_eval_manifest.jsonl'}")
    print(f"wrote eval word sets: {out_dir / 'minpair_eval_word_sets.json'}")
    print(f"wrote summary: {out_dir / 'minpair_manifest_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
