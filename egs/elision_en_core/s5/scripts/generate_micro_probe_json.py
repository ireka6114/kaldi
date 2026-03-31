#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a micro-probe JSON config from shared-core item/probe definitions.")
    ap.add_argument("--items-json", default="egs/elision_en_core/s5/config/elision_items.json")
    ap.add_argument("--probe-sets-json", default="egs/elision_en_core/s5/config/elision_probe_sets.json")
    ap.add_argument("--item-id", required=True)
    ap.add_argument("--output-json", required=True)
    ap.add_argument("--wrap-target", action="store_true", default=True)
    args = ap.parse_args()

    items = {item["item_id"]: item for item in load_json(Path(args.items_json).resolve())["items"]}
    probes = {entry["item_id"]: entry for entry in load_json(Path(args.probe_sets_json).resolve())["items"]}

    item = items[args.item_id]
    probe_entry = probes[args.item_id]
    probe = probe_entry.get("phoneme_deletion_probe") or probe_entry.get("syllable_deletion_probe")
    if probe is None:
        raise ValueError(f"no probe configured for item_id={args.item_id}")

    target_surface = probe["target"]
    target = f"__{target_surface}__" if args.wrap_target else target_surface
    competitors = [w for w in (probe.get("competitor_1"), probe.get("competitor_2")) if w]

    out = {
        "item": args.item_id.lower(),
        "probe_type": probe["probe_type"],
        "target": target,
        "competitors": competitors,
        "target_surface": target_surface,
        "whole_word": item["whole_word"],
        "deleted_part": item["deleted_part"],
        "group": item["group"],
    }
    Path(args.output_json).write_text(json.dumps(out, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
