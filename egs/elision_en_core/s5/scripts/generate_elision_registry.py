#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def read_words(words_txt: Path) -> set[str]:
    words = set()
    for line in words_txt.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 1:
            words.add(cols[0])
    return words


def write_list(path: Path, words: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(words) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate shared ELISION_EN_CORE probe registry.")
    ap.add_argument("--items-json", required=True)
    ap.add_argument("--probe-sets-json", required=True)
    ap.add_argument("--t02-rules-json", required=True)
    ap.add_argument("--words-txt", required=True)
    ap.add_argument("--word-list-dir", required=True)
    ap.add_argument("--grammar-fst-dir", required=True)
    ap.add_argument("--lang-dir", required=True)
    ap.add_argument("--manifest-path", required=True)
    ap.add_argument("--probe-manifest-path", required=True)
    args = ap.parse_args()

    items_cfg = json.loads(Path(args.items_json).read_text(encoding="utf-8"))
    probes_cfg = json.loads(Path(args.probe_sets_json).read_text(encoding="utf-8"))
    t02_rules = json.loads(Path(args.t02_rules_json).read_text(encoding="utf-8"))
    words_vocab = read_words(Path(args.words_txt))
    word_list_dir = Path(args.word_list_dir).resolve()
    grammar_fst_dir = Path(args.grammar_fst_dir).resolve()
    lang_dir = Path(args.lang_dir).resolve()

    items_by_id = {item["item_id"]: item for item in items_cfg.get("items", [])}
    dyn_defaults = t02_rules["dynamic_metadata_defaults"]
    entries = []
    probe_entries = []

    for probe_item in probes_cfg.get("items", []):
        item = items_by_id[probe_item["item_id"]]
        for probe_key in ("syllable_deletion_probe", "phoneme_deletion_probe"):
            probe = probe_item.get(probe_key)
            if not probe:
                continue
            graph_name = f"ELISION_{item['item_id']}_{probe['probe_type'].upper()}"
            candidates = probe["candidate_words"]
            missing = [w for w in candidates if w not in words_vocab]
            if missing:
                raise ValueError(f"{graph_name}: missing words in lang vocab: {missing}")

            word_list_path = word_list_dir / f"{graph_name}.lst"
            fst_path = grammar_fst_dir / f"{graph_name}.G.fst"
            write_list(word_list_path, candidates)

            entry = {
                "task_id": items_cfg["task_id"],
                "task_mode": "shared_core",
                "applicable_tasks": ["T01_EN", "T02_EN"],
                "graph_name": graph_name,
                "mode": "probe",
                "item_id": item["item_id"],
                "group": item["group"],
                "whole_word": item["whole_word"],
                "target_word": item["target_word"],
                "deleted_part": item["deleted_part"],
                "pseudo_word": bool(item["pseudo_word"]),
                "probe_type": probe["probe_type"],
                "candidate_words": candidates,
                "comparison_scope": probe["comparison_scope"],
                "grammar_fst_path": str(fst_path),
                "lang_dir": str(lang_dir),
                "graph_dir": None,
                "lang_graph_path": None,
                "prompt_level_support": dyn_defaults["prompt_level_support"],
                "teachable_error_types": dyn_defaults["teachable_error_types"],
                "suggested_feedback_type": dyn_defaults["suggested_feedback_type"],
                "retry_supported": dyn_defaults["retry_supported"]
            }
            entries.append(entry)
            probe_entries.append(dict(entry))

    manifest = {
        "task_id": items_cfg["task_id"],
        "core_name": "ELISION_EN_CORE",
        "dict_name": "dict_ELISION_EN",
        "lang_name": "lang_elision_en",
        "entries": entries,
    }
    probe_manifest = {
        "task_id": items_cfg["task_id"],
        "core_name": "ELISION_EN_CORE",
        "entries": probe_entries,
    }

    Path(args.manifest_path).write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(args.probe_manifest_path).write_text(
        json.dumps(probe_manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
