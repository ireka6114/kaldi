#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare T01 static trial manifest from shared ELISION_EN_CORE assets.")
    ap.add_argument("--items-json", default="egs/elision_en_core/s5/config/elision_items.json")
    ap.add_argument("--t01-rules-json", default="egs/elision_en_core/s5/config/t01_static_rules.json")
    ap.add_argument("--probe-manifest", default="egs/elision_en_core/s5/runtime/manifests/elision_probe_manifest.json")
    ap.add_argument("--wav-root", required=True)
    ap.add_argument("--output-json", required=True)
    args = ap.parse_args()

    items = {item["item_id"]: item for item in json.loads(Path(args.items_json).read_text(encoding="utf-8"))["items"]}
    rules = json.loads(Path(args.t01_rules_json).read_text(encoding="utf-8"))
    probe_manifest = json.loads(Path(args.probe_manifest).read_text(encoding="utf-8"))["entries"]
    probe_by_item = {entry["item_id"]: entry for entry in probe_manifest}
    wav_root = Path(args.wav_root).resolve()

    trials = []
    for item_id in rules["item_order"]:
        item = items[item_id]
        entry = probe_by_item[item_id]
        utt_id = f"t01_{item_id.lower()}"
        trials.append(
            {
                "utt_id": utt_id,
                "task_id": "T01_EN_STATIC",
                "item_id": item_id,
                "group": item["group"],
                "graph_name": entry["graph_name"],
                "wav_path": str(wav_root / f"{item['whole_word']}.wav"),
            }
        )

    out = {
        "task_id": "T01_EN_STATIC",
        "core_task_id": "ELISION_EN_CORE",
        "entries": trials,
    }
    Path(args.output_json).write_text(json.dumps(out, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
