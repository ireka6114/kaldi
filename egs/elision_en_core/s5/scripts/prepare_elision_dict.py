#!/usr/bin/env python3

import argparse
import csv
import json
from pathlib import Path


SPECIAL_LEXICON = [
    ("!SIL", ["SIL"]),
    ("<UNK>", ["SPN"]),
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_delta(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if not rows:
        raise ValueError(f"delta file is empty: {path}")

    required = {"item_id", "group", "surface_role", "surface", "pseudo_word", "phone_source", "phones"}
    missing = required.difference(rows[0].keys())
    if missing:
        raise ValueError(f"delta header missing columns: {sorted(missing)}")

    parsed = []
    seen_surface = set()
    for row in rows:
        surface = row["surface"].strip()
        if not surface:
            raise ValueError("empty surface in delta row")
        if surface in seen_surface:
            raise ValueError(f"duplicate surface in delta: {surface}")
        seen_surface.add(surface)

        phones = [p for p in row["phones"].strip().split() if p]
        if not phones:
            raise ValueError(f"missing phones for surface={surface}")

        parsed.append(
            {
                "item_id": row["item_id"].strip(),
                "group": row["group"].strip(),
                "surface_role": row["surface_role"].strip(),
                "surface": surface,
                "pseudo_word": row["pseudo_word"].strip().lower() == "true",
                "phone_source": row["phone_source"].strip(),
                "phones": phones,
            }
        )
    return parsed


def validate_item_coverage(items_cfg: dict, delta_rows: list[dict]) -> None:
    by_item_role = {(row["item_id"], row["surface_role"]): row for row in delta_rows}

    for item in items_cfg.get("items", []):
        item_id = item["item_id"]
        for role, item_key in (
            ("whole_word", "whole_word"),
            ("target_word", "target_word"),
            ("deleted_part", "deleted_part"),
        ):
            row = by_item_role.get((item_id, role))
            if row is None:
                raise ValueError(f"delta missing required row: item_id={item_id} role={role}")
            if row["surface"] != item[item_key]:
                raise ValueError(
                    f"delta surface mismatch: item_id={item_id} role={role} "
                    f"delta={row['surface']} config={item[item_key]}"
                )
            expected_phones = item["phone_sequences"][role]
            if row["phones"] != expected_phones:
                raise ValueError(
                    f"delta phones mismatch: item_id={item_id} role={role} "
                    f"delta={row['phones']} config={expected_phones}"
                )

        whole = by_item_role[(item_id, "whole_word")]["phones"]
        target = by_item_role[(item_id, "target_word")]["phones"]
        deleted = by_item_role[(item_id, "deleted_part")]["phones"]

        if whole[: len(deleted)] != deleted:
            raise ValueError(f"deleted_part prefix mismatch for item_id={item_id}")
        if whole[len(deleted) :] != target:
            raise ValueError(f"target suffix mismatch for item_id={item_id}")

        if item["group"] == "B" and item.get("pseudo_word"):
            target_row = by_item_role[(item_id, "target_word")]
            if target_row["phone_source"] != "manual":
                raise ValueError(f"B-group pseudo-word requires manual phones: item_id={item_id}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build shared dict_ELISION_EN from lexicon delta, then merge into lexicon.txt / lexiconp.txt.")
    ap.add_argument("--items-json", required=True)
    ap.add_argument("--lexicon-delta-tsv", required=True)
    ap.add_argument("--dict-dir", required=True)
    args = ap.parse_args()

    items_cfg = load_json(Path(args.items_json).resolve())
    delta_rows = load_delta(Path(args.lexicon_delta_tsv).resolve())
    validate_item_coverage(items_cfg, delta_rows)

    dict_dir = Path(args.dict_dir).resolve()
    dict_dir.mkdir(parents=True, exist_ok=True)

    ordered_rows = sorted(delta_rows, key=lambda row: row["surface"])
    delta_lines = [f"{row['surface']} {' '.join(row['phones'])}" for row in ordered_rows]
    lexicon_lines = [f"{word} {' '.join(phones)}" for word, phones in SPECIAL_LEXICON] + delta_lines
    lexiconp_lines = [f"{word} 1.0 {' '.join(phones)}" for word, phones in SPECIAL_LEXICON] + [
        f"{row['surface']} 1.0 {' '.join(row['phones'])}" for row in ordered_rows
    ]

    nonsilence = sorted({phone for row in ordered_rows for phone in row["phones"]})
    (dict_dir / "lexicon.delta.txt").write_text("\n".join(delta_lines) + "\n", encoding="utf-8")
    (dict_dir / "lexicon.txt").write_text("\n".join(lexicon_lines) + "\n", encoding="utf-8")
    (dict_dir / "lexiconp.txt").write_text("\n".join(lexiconp_lines) + "\n", encoding="utf-8")
    (dict_dir / "nonsilence_phones.txt").write_text("\n".join(nonsilence) + "\n", encoding="utf-8")
    (dict_dir / "silence_phones.txt").write_text("SIL\nSPN\n", encoding="utf-8")
    (dict_dir / "optional_silence.txt").write_text("SIL\n", encoding="utf-8")
    (dict_dir / "extra_questions.txt").write_text("\n".join(nonsilence) + "\n", encoding="utf-8")

    manifest = {
        "task_id": items_cfg.get("task_id"),
        "dict_name": "dict_ELISION_EN",
        "delta_path": str(Path(args.lexicon_delta_tsv).resolve()),
        "delta_surface_count": len(ordered_rows),
        "merged_word_count": len(ordered_rows) + len(SPECIAL_LEXICON),
        "shared_between_tasks": ["T01_EN", "T02_EN"],
    }
    (dict_dir / "dict_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
