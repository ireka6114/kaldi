#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def read_words(words_txt: Path) -> set[str]:
    words = set()
    for line in words_txt.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        token = line.split()[0]
        words.add(token)
    return words


def write_list(path: Path, words: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(words) + "\n", encoding="utf-8")


def unique_preserve_order(words: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for w in words:
        if w not in seen:
            seen.add(w)
            ordered.append(w)
    return ordered


def find_confusion_group(level_info: dict, target: str) -> list[str]:
    groups = level_info.get("confusion_groups", [])
    for group in groups:
        ordered = unique_preserve_order(group)
        if target in ordered:
            return ordered
    return [target]


def long_short_pair(word: str, vocab: set[str]) -> str | None:
    if word.endswith("e"):
        short = word[:-1]
        return short if short in vocab else None
    long = f"{word}e"
    return long if long in vocab else None


def ing_pattern_pair(word: str, vocab: set[str]) -> str | None:
    if word.endswith("tting"):
        cand = f"{word[:-5]}ting"
        return cand if cand in vocab else None
    if word.endswith("pping"):
        cand = f"{word[:-5]}ping"
        return cand if cand in vocab else None
    if word.endswith("ting"):
        cand = f"{word[:-4]}tting"
        return cand if cand in vocab else None
    if word.endswith("ping"):
        cand = f"{word[:-4]}pping"
        return cand if cand in vocab else None
    return None


def load_family_safe_index(confusion_cfg: dict) -> tuple[dict[str, dict], dict[str, set[str]]]:
    formal_default = confusion_cfg.get("formal_default", {})
    families = formal_default.get("families", [])
    if not families:
        raise ValueError("confusion config formal_default.families is empty")

    target_index: dict[str, dict] = {}
    family_vocab: dict[str, set[str]] = {}

    for fam in families:
        family_name = fam["family_name"]
        dim = fam["diagnostic_dimension"]
        items = fam.get("items", {})
        vocab = set(items.keys())
        family_vocab[family_name] = vocab

        for target, cands_raw in items.items():
            cands = unique_preserve_order(cands_raw)
            if target not in cands:
                raise ValueError(f"family={family_name} target={target} missing self in candidates")
            extra = [w for w in cands if w not in vocab]
            if extra:
                raise ValueError(
                    f"family={family_name} target={target} has cross-family candidates: {extra}"
                )
            if target in target_index:
                raise ValueError(f"target duplicated across families: {target}")
            target_index[target] = {
                "family_name": family_name,
                "diagnostic_dimension": dim,
                "candidates": cands,
            }

    return target_index, family_vocab


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-json", required=True)
    ap.add_argument("--confusion-config-json", required=True)
    ap.add_argument("--words-txt", required=True)
    ap.add_argument("--word-list-dir", required=True)
    ap.add_argument("--grammar-fst-dir", required=True)
    ap.add_argument("--lang-dir", required=True)
    ap.add_argument("--manifest-path", required=True)
    ap.add_argument("--probe-manifest-path", default="")
    ap.add_argument("--include-item-aware", action="store_true")
    ap.add_argument("--include-pseudoword-diagnostics", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config_json).resolve()
    confusion_path = Path(args.confusion_config_json).resolve()
    words_txt = Path(args.words_txt).resolve()
    word_list_dir = Path(args.word_list_dir).resolve()
    grammar_fst_dir = Path(args.grammar_fst_dir).resolve()
    lang_dir = Path(args.lang_dir).resolve()
    manifest_path = Path(args.manifest_path).resolve()
    probe_manifest_path = Path(args.probe_manifest_path).resolve() if args.probe_manifest_path else None

    config = json.loads(config_path.read_text(encoding="utf-8"))
    confusion_cfg = json.loads(confusion_path.read_text(encoding="utf-8"))

    if config.get("task_id") != confusion_cfg.get("task_id"):
        raise ValueError(
            f"task_id mismatch: {config.get('task_id')} vs {confusion_cfg.get('task_id')}"
        )

    words_vocab = read_words(words_txt)
    task_id = config["task_id"]
    entries = []
    probe_entries = []

    target_index, _ = load_family_safe_index(confusion_cfg)

    def append_entry(
        graph_name: str,
        mode: str,
        level: str,
        item_key: str | None,
        candidates: list[str],
        formal: bool,
        notes: str,
        source_set: str,
        candidate_policy: str,
        family_name: str | None,
        diagnostic_dimension: str | None,
        is_formal_default: bool,
        probe_type: str | None = None,
        is_formal_probe: bool = False,
        target_word: str | None = None,
        parent_level_graph: str | None = None,
    ) -> None:
        missing = [w for w in candidates if w not in words_vocab]
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

    formal_levels = config["formal_levels"]
    for graph_name, info in formal_levels.items():
        candidates = unique_preserve_order(info["words"])
        levels = info.get("uses_levels", [])
        level_note = f"uses_levels={','.join(levels)}" if levels else "uses_levels=none"
        append_entry(
            graph_name=graph_name,
            mode="level",
            level=info["level_tag"],
            item_key=None,
            candidates=candidates,
            formal=True,
            notes=f"formal level graph; {level_note}",
            source_set=info["source_set"],
            candidate_policy="level",
            family_name=None,
            diagnostic_dimension=None,
            is_formal_default=False,
            probe_type=None,
            is_formal_probe=False,
            target_word=None,
            parent_level_graph=graph_name,
        )

    for graph_name, info in config["demo_levels"].items():
        candidates = unique_preserve_order(info["words"])
        append_entry(
            graph_name=graph_name,
            mode="demo",
            level=info["level_tag"],
            item_key=None,
            candidates=candidates,
            formal=False,
            notes="demo graph",
            source_set=info["source_set"],
            candidate_policy="demo",
            family_name=None,
            diagnostic_dimension=None,
            is_formal_default=False,
            probe_type=None,
            is_formal_probe=False,
            target_word=None,
            parent_level_graph=graph_name,
        )

    if args.include_item_aware:
        level_all_policy = confusion_cfg.get("diagnostic_level_all", {}).get(
            "candidate_policy", "diagnostic_level_all"
        )
        family_policy = confusion_cfg.get("formal_default", {}).get(
            "candidate_policy", "item_plus_confusion_family_safe"
        )

        for level_graph_name, info in formal_levels.items():
            level_words = unique_preserve_order(info["words"])
            for target in level_words:
                fam = target_index.get(target)
                if not fam:
                    raise ValueError(f"formal target missing family-safe confusion definition: {target}")

                append_entry(
                    graph_name=f"T04_ITEM_{level_graph_name}_{target}_SINGLE",
                    mode="item",
                    level=info["level_tag"],
                    item_key=target,
                    candidates=[target],
                    formal=False,
                    notes=f"item-aware variant=single parent_level={level_graph_name}",
                    source_set=info["source_set"],
                    candidate_policy="single",
                    family_name=fam["family_name"],
                    diagnostic_dimension=fam["diagnostic_dimension"],
                    is_formal_default=False,
                    probe_type=None,
                    is_formal_probe=False,
                    target_word=target,
                    parent_level_graph=level_graph_name,
                )
                append_entry(
                    graph_name=f"T04_ITEM_{level_graph_name}_{target}_FAMILY_SAFE",
                    mode="item",
                    level=info["level_tag"],
                    item_key=target,
                    candidates=fam["candidates"],
                    formal=False,
                    notes=(
                        "item-aware variant=item_plus_confusion_family_safe auxiliary_mode "
                        f"parent_level={level_graph_name}"
                    ),
                    source_set=info["source_set"],
                    candidate_policy=family_policy,
                    family_name=fam["family_name"],
                    diagnostic_dimension=fam["diagnostic_dimension"],
                    is_formal_default=False,
                    probe_type=None,
                    is_formal_probe=False,
                    target_word=target,
                    parent_level_graph=level_graph_name,
                )
                append_entry(
                    graph_name=f"T04_ITEM_{level_graph_name}_{target}_LEVEL_ALL",
                    mode="item",
                    level=info["level_tag"],
                    item_key=target,
                    candidates=level_words,
                    formal=False,
                    notes=f"item-aware variant=level_all parent_level={level_graph_name}",
                    source_set=info["source_set"],
                    candidate_policy=level_all_policy,
                    family_name=fam["family_name"],
                    diagnostic_dimension=fam["diagnostic_dimension"],
                    is_formal_default=False,
                    probe_type=None,
                    is_formal_probe=False,
                    target_word=target,
                    parent_level_graph=level_graph_name,
                )

        for level_graph_name, info in formal_levels.items():
            level_words = unique_preserve_order(info["words"])
            for target in level_words:
                onset_cands = find_confusion_group(info, target)
                append_entry(
                    graph_name=f"T04_PROBE_{level_graph_name}_{target}_ONSET",
                    mode="probe",
                    level=info["level_tag"],
                    item_key=target,
                    candidates=onset_cands,
                    formal=True,
                    notes=f"micro-probe onset_probe parent_level={level_graph_name}",
                    source_set=info["source_set"],
                    candidate_policy="candidate_specific_micro_probe",
                    family_name=target_index.get(target, {}).get("family_name"),
                    diagnostic_dimension="onset",
                    is_formal_default=True,
                    probe_type="onset_probe",
                    is_formal_probe=True,
                    target_word=target,
                    parent_level_graph=level_graph_name,
                )

                pair = long_short_pair(target, words_vocab)
                if pair is not None:
                    append_entry(
                        graph_name=f"T04_PROBE_{level_graph_name}_{target}_VOWEL",
                        mode="probe",
                        level=info["level_tag"],
                        item_key=target,
                        candidates=[target, pair],
                        formal=True,
                        notes=f"micro-probe vowel_probe parent_level={level_graph_name}",
                        source_set=info["source_set"],
                        candidate_policy="candidate_specific_micro_probe",
                        family_name=target_index.get(target, {}).get("family_name"),
                        diagnostic_dimension="vowel_length",
                        is_formal_default=True,
                        probe_type="vowel_probe",
                        is_formal_probe=True,
                        target_word=target,
                        parent_level_graph=level_graph_name,
                    )

                pattern_pair = ing_pattern_pair(target, words_vocab)
                if pattern_pair is not None:
                    append_entry(
                        graph_name=f"T04_PROBE_{level_graph_name}_{target}_PATTERN",
                        mode="probe",
                        level=info["level_tag"],
                        item_key=target,
                        candidates=[target, pattern_pair],
                        formal=True,
                        notes=f"micro-probe pattern_probe parent_level={level_graph_name}",
                        source_set=info["source_set"],
                        candidate_policy="candidate_specific_micro_probe",
                        family_name=target_index.get(target, {}).get("family_name"),
                        diagnostic_dimension="ing_pattern",
                        is_formal_default=True,
                        probe_type="pattern_probe",
                        is_formal_probe=True,
                        target_word=target,
                        parent_level_graph=level_graph_name,
                    )

    if args.include_pseudoword_diagnostics:
        pseudo_cfg = confusion_cfg.get("optional_pseudoword_diagnostics", {})
        pseudo_items = pseudo_cfg.get("items", {})
        for pseudo_target, raw_cands in pseudo_items.items():
            cands = unique_preserve_order(raw_cands)
            append_entry(
                graph_name=f"T04_PSEUDO_{pseudo_target.strip('_')}_DIAG",
                mode="diagnostic",
                level="DIAG",
                item_key=pseudo_target,
                candidates=cands,
                formal=False,
                notes="optional pseudoword diagnostics",
                source_set="PSEUDOWORD_DIAG",
                candidate_policy=pseudo_cfg.get("candidate_policy", "optional_pseudoword_diagnostics"),
                family_name=None,
                diagnostic_dimension="pseudoword",
                is_formal_default=False,
                probe_type=None,
                is_formal_probe=False,
                target_word=pseudo_target,
                parent_level_graph=None,
            )

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "task_id": task_id,
        "config": {
            "word_sets": str(config_path),
            "confusion_sets": str(confusion_path),
            "include_item_aware": bool(args.include_item_aware),
            "include_pseudoword_diagnostics": bool(args.include_pseudoword_diagnostics),
            "formal_diagnostic_default": "candidate_specific_micro_probe",
        },
        "entries": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote manifest: {manifest_path} ({len(entries)} entries)")

    if probe_manifest_path:
        probe_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        probe_manifest = {
            "task_id": task_id,
            "config": {
                "word_sets": str(config_path),
                "confusion_sets": str(confusion_path),
                "source_manifest": str(manifest_path),
                "formal_diagnostic_default": "candidate_specific_micro_probe",
            },
            "entries": probe_entries,
        }
        probe_manifest_path.write_text(
            json.dumps(probe_manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote probe manifest: {probe_manifest_path} ({len(probe_entries)} entries)")


if __name__ == "__main__":
    main()
