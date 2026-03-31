#!/usr/bin/env python3

import argparse
import csv
import json
from pathlib import Path


def read_words(words_txt: Path) -> set[str]:
    words = set()
    for line in words_txt.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        words.add(line.split()[0])
    return words


def read_items(items_csv: Path) -> dict[str, dict]:
    items = {}
    with items_csv.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            word_id = row["word_id"].strip()
            items[word_id] = {
                "surface_form": row["surface_form"].strip(),
                "phone_sequence": row["phone_sequence"].strip(),
                "onset_probe_words": split_words(row.get("onset_probe_words", "")),
                "final_probe_words": split_words(row.get("final_probe_words", "")),
                "tone_probe_words": split_words(row.get("tone_probe_words", "")),
                "notes": row.get("notes", "").strip(),
            }
    return items


def split_words(raw: str) -> list[str]:
    words = []
    for token in raw.split("|"):
        token = token.strip()
        if token:
            words.append(token)
    return unique_preserve_order(words)


def unique_preserve_order(words: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        ordered.append(word)
    return ordered


def write_list(path: Path, words: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(words) + "\n", encoding="utf-8")


def load_family_index(confusion_cfg: dict) -> dict[str, dict]:
    families = confusion_cfg.get("formal_default", {}).get("families", [])
    index = {}
    for fam in families:
        for target, cands_raw in fam.get("items", {}).items():
            index[target] = {
                "family_name": fam["family_name"],
                "diagnostic_dimension": fam["diagnostic_dimension"],
                "candidates": unique_preserve_order(cands_raw),
            }
    return index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-json", required=True)
    ap.add_argument("--confusion-config-json", required=True)
    ap.add_argument("--items-csv", required=True)
    ap.add_argument("--words-txt", required=True)
    ap.add_argument("--word-list-dir", required=True)
    ap.add_argument("--grammar-fst-dir", required=True)
    ap.add_argument("--lang-dir", required=True)
    ap.add_argument("--manifest-path", required=True)
    ap.add_argument("--probe-manifest-path", default="")
    ap.add_argument("--include-item-aware", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config_json).resolve()
    confusion_path = Path(args.confusion_config_json).resolve()
    items_csv = Path(args.items_csv).resolve()
    words_txt = Path(args.words_txt).resolve()
    word_list_dir = Path(args.word_list_dir).resolve()
    grammar_fst_dir = Path(args.grammar_fst_dir).resolve()
    lang_dir = Path(args.lang_dir).resolve()
    manifest_path = Path(args.manifest_path).resolve()
    probe_manifest_path = Path(args.probe_manifest_path).resolve() if args.probe_manifest_path else None

    config = json.loads(config_path.read_text(encoding="utf-8"))
    confusion_cfg = json.loads(confusion_path.read_text(encoding="utf-8"))
    items = read_items(items_csv)
    words_vocab = read_words(words_txt)
    family_index = load_family_index(confusion_cfg)
    entries = []
    probe_entries = []
    task_id = config["task_id"]

    if task_id != confusion_cfg.get("task_id"):
        raise ValueError(
            f"task_id mismatch: {task_id} vs {confusion_cfg.get('task_id')}"
        )

    def append_entry(
        graph_name: str,
        mode: str,
        level: str,
        item_key: str | None,
        target_word: str | None,
        candidates: list[str],
        source_set: str,
        notes: str,
        candidate_policy: str,
        diagnostic_dimension: str | None = None,
        probe_type: str | None = None,
        family_name: str | None = None,
        parent_level_graph: str | None = None,
        formal: bool = False,
        is_formal_default: bool = False,
        is_formal_probe: bool = False,
    ) -> None:
        missing = [word for word in candidates if word not in words_vocab]
        if missing:
            raise ValueError(f"{graph_name}: words not in {words_txt}: {missing}")

        list_path = word_list_dir / f"{graph_name}.lst"
        fst_path = grammar_fst_dir / f"{graph_name}.G.fst"
        write_list(list_path, candidates)
        entries.append(
            {
                "task_id": task_id,
                "graph_name": graph_name,
                "mode": mode,
                "level": level,
                "item_key": item_key,
                "target_word": target_word,
                "candidate_words": candidates,
                "grammar_fst_path": str(fst_path),
                "lang_dir": str(lang_dir),
                "graph_dir": None,
                "whether_formal_response": formal,
                "is_formal_default": is_formal_default,
                "is_formal_probe": is_formal_probe,
                "candidate_policy": candidate_policy,
                "family_name": family_name,
                "diagnostic_dimension": diagnostic_dimension,
                "diagnostic_dimension_hint": diagnostic_dimension,
                "probe_type": probe_type,
                "parent_level_graph": parent_level_graph,
                "notes": notes,
                "source_set": source_set,
            }
        )
        if mode == "probe":
            probe_entries.append(
                {
                    "task_id": task_id,
                    "graph_name": graph_name,
                    "parent_level_graph": parent_level_graph,
                    "target_word": target_word,
                    "probe_type": probe_type,
                    "candidate_words": candidates,
                    "lang_graph_path": None,
                    "graph_path": None,
                    "diagnostic_dimension": diagnostic_dimension,
                    "diagnostic_dimension_hint": diagnostic_dimension,
                    "candidate_policy": candidate_policy,
                    "is_formal_probe": is_formal_probe,
                    "source_set": source_set,
                    "level": level,
                }
            )

    for graph_name, info in config["formal_levels"].items():
        candidates = unique_preserve_order(info["words"])
        append_entry(
            graph_name=graph_name,
            mode="level",
            level=info["level_tag"],
            item_key=None,
            target_word=None,
            candidates=candidates,
            source_set=info["source_set"],
            notes="formal level graph",
            candidate_policy="level",
            parent_level_graph=graph_name,
            formal=True,
        )

        for target in candidates:
            item = items[target]
            if args.include_item_aware:
                fam = family_index.get(target, {})
                append_entry(
                    graph_name=f"T12_ITEM_{graph_name}_{target}_BUNDLE",
                    mode="item",
                    level=info["level_tag"],
                    item_key=target,
                    target_word=target,
                    candidates=fam.get("candidates", [target]),
                    source_set=info["source_set"],
                    notes="item-aware bundle",
                    candidate_policy="item_plus_confusion_bundle",
                    diagnostic_dimension=fam.get("diagnostic_dimension", "composite_pinyin"),
                    family_name=fam.get("family_name"),
                    parent_level_graph=graph_name,
                )

            probe_specs = [
                ("onset_probe", "onset", item["onset_probe_words"], "ONSET"),
                ("final_probe", "final", item["final_probe_words"], "FINAL"),
                ("tone_probe", "tone", item["tone_probe_words"], "TONE"),
            ]
            for probe_type, dimension, probe_words, suffix in probe_specs:
                if not probe_words:
                    continue
                append_entry(
                    graph_name=f"T12_PROBE_{graph_name}_{target}_{suffix}",
                    mode="probe",
                    level=info["level_tag"],
                    item_key=target,
                    target_word=target,
                    candidates=probe_words,
                    source_set=info["source_set"],
                    notes=f"micro-probe {probe_type}; surface={item['surface_form']}",
                    candidate_policy="candidate_specific_micro_probe",
                    diagnostic_dimension=dimension,
                    probe_type=probe_type,
                    family_name=None,
                    parent_level_graph=graph_name,
                    formal=True,
                    is_formal_default=True,
                    is_formal_probe=True,
                )

    manifest = {
        "task_id": task_id,
        "config": {
            "word_sets": str(config_path),
            "confusion_sets": str(confusion_path),
            "items_csv": str(items_csv),
            "include_item_aware": bool(args.include_item_aware),
            "formal_diagnostic_default": "candidate_specific_micro_probe",
        },
        "entries": entries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote manifest: {manifest_path} ({len(entries)} entries)")

    if probe_manifest_path:
        probe_manifest = {
            "task_id": task_id,
            "config": {
                "word_sets": str(config_path),
                "confusion_sets": str(confusion_path),
                "items_csv": str(items_csv),
                "source_manifest": str(manifest_path),
                "formal_diagnostic_default": "candidate_specific_micro_probe",
            },
            "entries": probe_entries,
        }
        probe_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        probe_manifest_path.write_text(
            json.dumps(probe_manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote probe manifest: {probe_manifest_path} ({len(probe_entries)} entries)")


if __name__ == "__main__":
    main()
