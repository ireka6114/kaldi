#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def load_error_ids(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare T02 dynamic trial manifest from the first T01 error item through the end of the shared order.")
    ap.add_argument("--items-json", default="egs/elision_en_core/s5/config/elision_items.json")
    ap.add_argument("--t01-rules-json", default="egs/elision_en_core/s5/config/t01_static_rules.json")
    ap.add_argument("--t02-rules-json", default="egs/elision_en_core/s5/config/t02_dynamic_rules.json")
    ap.add_argument("--probe-manifest", default="egs/elision_en_core/s5/runtime/manifests/elision_probe_manifest.json")
    ap.add_argument("--error-item-ids", required=True)
    ap.add_argument("--wav-root", required=True)
    ap.add_argument("--output-json", required=True)
    args = ap.parse_args()

    items = {item["item_id"]: item for item in json.loads(Path(args.items_json).read_text(encoding="utf-8"))["items"]}
    t01_rules = json.loads(Path(args.t01_rules_json).read_text(encoding="utf-8"))
    t02_rules = json.loads(Path(args.t02_rules_json).read_text(encoding="utf-8"))
    probe_manifest = json.loads(Path(args.probe_manifest).read_text(encoding="utf-8"))["entries"]
    probe_by_item = {entry["item_id"]: entry for entry in probe_manifest}
    wav_root = Path(args.wav_root).resolve()
    error_ids = set(load_error_ids(Path(args.error_item_ids).resolve()))
    item_order = t01_rules["item_order"]

    first_error_idx = None
    for idx, item_id in enumerate(item_order):
        if item_id in error_ids:
            first_error_idx = idx
            break

    trials = []
    if first_error_idx is None:
        suffix_items = []
    else:
        suffix_items = item_order[first_error_idx:]

    for offset, item_id in enumerate(suffix_items):
        if item_id not in items or item_id not in probe_by_item:
            continue
        item = items[item_id]
        entry = probe_by_item[item_id]
        utt_id = f"t02_{item_id.lower()}"
        trials.append(
            {
                "utt_id": utt_id,
                "task_id": "T02_EN_DYNAMIC",
                "item_id": item_id,
                "group": item["group"],
                "graph_name": entry["graph_name"],
                "wav_path": str(wav_root / f"{item['whole_word']}.wav"),
                "sequence_index": offset,
                "starts_at_first_t01_error": offset == 0,
                "triggered_by_t01_error": item_id in error_ids,
                "prompt_level_support": entry["prompt_level_support"],
                "retry_supported": entry["retry_supported"],
            }
        )

    out = {
        "task_id": "T02_EN_DYNAMIC",
        "core_task_id": "ELISION_EN_CORE",
        "entry_condition": t02_rules["entry_condition"],
        "t01_first_error_item_id": suffix_items[0] if suffix_items else None,
        "entries": trials,
    }
    Path(args.output_json).write_text(json.dumps(out, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
