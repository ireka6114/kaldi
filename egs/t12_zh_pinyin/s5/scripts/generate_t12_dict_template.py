#!/usr/bin/env python3

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

INITIALS = (
    "zh",
    "ch",
    "sh",
    "b",
    "p",
    "m",
    "f",
    "d",
    "t",
    "n",
    "l",
    "g",
    "k",
    "h",
    "j",
    "q",
    "x",
    "r",
    "z",
    "c",
    "s",
    "y",
    "w",
)

SPECIAL_LEXICON = {
    "!SIL": ["SIL"],
    "<UNK>": ["SPN"],
}
SPECIAL_PHONE_ALIASES = {
    "SIL": ["SIL", "sil"],
    "SPN": ["SPN", "spn"],
    "NSN": ["NSN", "nsn"],
}
DEFAULT_PINYIN_MAP = Path(__file__).resolve().parents[3] / "multi_cn/s5/conf/pinyin2cmu"


def split_words(raw: str) -> list[str]:
    return [token.strip() for token in raw.split("|") if token.strip()]


def parse_word_tone(word_id: str) -> str | None:
    match = re.fullmatch(r"([a-z]+)([1-4])", word_id)
    if not match:
        return None
    return match.group(2)


def parse_numbered_pinyin(word_id: str) -> tuple[str, str]:
    match = re.fullmatch(r"([a-z]+)([1-4])", word_id)
    if not match:
        raise ValueError(f"Unsupported word_id format: {word_id}")
    base, tone = match.groups()
    for initial in INITIALS:
        if base.startswith(initial):
            final = base[len(initial) :]
            if not final:
                break
            return initial, f"{final}{tone}"
    raise ValueError(f"Unable to derive phones from numbered pinyin: {word_id}")


def load_items(items_csv: Path) -> dict[str, dict]:
    items = {}
    with items_csv.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            word_id = row["word_id"].strip()
            items[word_id] = {
                "surface_form": row["surface_form"].strip(),
                "phone_sequence": row["phone_sequence"].strip().split(),
                "onset_probe_words": split_words(row.get("onset_probe_words", "")),
                "final_probe_words": split_words(row.get("final_probe_words", "")),
                "tone_probe_words": split_words(row.get("tone_probe_words", "")),
                "notes": row.get("notes", "").strip(),
            }
    return items


def collect_all_words(items: dict[str, dict]) -> list[str]:
    ordered = []
    seen = set()
    for word_id, info in items.items():
        for token in [word_id, *info["onset_probe_words"], *info["final_probe_words"], *info["tone_probe_words"]]:
            if token not in seen:
                seen.add(token)
                ordered.append(token)
    return ordered


def derive_lexicon(items: dict[str, dict], all_words: list[str]) -> dict[str, list[str]]:
    lexicon = {}
    for word_id in all_words:
        if word_id in items:
            lexicon[word_id] = items[word_id]["phone_sequence"]
            continue
        initial, final = parse_numbered_pinyin(word_id)
        lexicon[word_id] = [initial, final]
    lexicon.update(SPECIAL_LEXICON)
    return lexicon


def split_final_tone(final: str) -> tuple[str, str]:
    match = re.fullmatch(r"([a-z]+)([1-4])", final)
    if not match:
        raise ValueError(f"Unsupported final format: {final}")
    return match.groups()


def split_final_optional_tone(final: str) -> tuple[str, str | None]:
    match = re.fullmatch(r"([a-z]+?)([1-4])?$", final)
    if not match:
        raise ValueError(f"Unsupported final format: {final}")
    return match.group(1), match.group(2)


def canonicalize_final_base(final_base: str) -> str:
    base = final_base.lower().replace("ü", "v")
    if base.endswith("ue"):
        base = base[:-2] + "ve"
    return base


def load_pinyin_map(pinyin_map_path: Path) -> dict[str, list[str]]:
    mapping = {}
    for line in pinyin_map_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        mapping[parts[0]] = parts[1:]
    return mapping


def load_phone_symbols(phones_txt: Path) -> set[str]:
    symbols = set()
    for line in phones_txt.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            symbols.add(parts[0])
    return symbols


def normalize_phone_symbol(phone: str) -> str:
    return re.sub(r"_[BEIS]$", "", phone)


def tone_family_key(phone: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+?)(\d+)?", phone)
    if not match:
        return phone, -1
    stem, tone = match.groups()
    return stem, int(tone) if tone is not None else 0


def build_model_phone_inventory(
    phone_symbols: set[str],
) -> tuple[list[str], list[str]]:
    normalized_symbols = {
        normalize_phone_symbol(symbol)
        for symbol in phone_symbols
        if symbol and symbol != "<eps>" and not symbol.startswith("#")
    }
    silence_bases = ["SIL", "SPN", "NSN"]
    silence_lines = [phone for phone in silence_bases if phone in normalized_symbols]

    grouped: dict[str, set[str]] = defaultdict(set)
    for phone in normalized_symbols:
        if phone in silence_bases:
            continue
        root = re.sub(r"\d+$", "", phone)
        grouped[root].add(phone)

    nonsilence_lines = []
    for root in sorted(grouped):
        variants = sorted(grouped[root], key=tone_family_key)
        nonsilence_lines.append(" ".join(variants))
    return silence_lines, nonsilence_lines


def resolve_special_phone(phone: str, phone_symbols: set[str]) -> str:
    for candidate in SPECIAL_PHONE_ALIASES.get(phone, [phone]):
        if candidate in phone_symbols:
            return candidate
    raise ValueError(f"Missing special phone in provided phones.txt: {phone}")


def map_intermediate_syllable_to_multi_cn(
    word_id: str, seq: list[str], pinyin_map: dict[str, list[str]]
) -> tuple[list[str], list[str], list[str]]:
    if len(seq) != 2:
        raise ValueError(f"Expected two-part intermediate syllable, got {seq}")
    onset, final = seq
    final_base_raw, seq_tone = split_final_optional_tone(final)
    tone = parse_word_tone(word_id) or seq_tone
    if tone is None:
        raise ValueError(f"Unable to derive tone from word_id/final: {word_id} -> {seq}")
    onset_key = onset.upper()
    final_key = canonicalize_final_base(final_base_raw).upper()
    if onset_key not in pinyin_map:
        raise ValueError(f"Missing onset mapping for {onset_key}")
    if final_key not in pinyin_map:
        raise ValueError(f"Missing final mapping for {final_key}")
    onset_phones = list(pinyin_map[onset_key])
    final_phones = list(pinyin_map[final_key])
    return onset_phones + final_phones, onset_phones, final_phones


def map_lexicon_to_existing_phones(
    lexicon: dict[str, list[str]],
    phone_symbols: set[str],
    pinyin_map: dict[str, list[str]] | None,
    fail_on_missing_phone: bool,
) -> tuple[dict[str, list[str]], dict[str, dict[str, list[str]]], list[str]]:
    mapped = {}
    components = {}
    missing = set()
    normalized_phone_symbols = {normalize_phone_symbol(phone) for phone in phone_symbols}

    for word_id, seq in lexicon.items():
        if word_id in SPECIAL_LEXICON:
            mapped_seq = []
            for phone in seq:
                try:
                    mapped_seq.append(resolve_special_phone(phone, phone_symbols))
                except ValueError:
                    missing.add(phone)
            if len(mapped_seq) == len(seq):
                mapped[word_id] = mapped_seq
            continue

        candidate_seq = None
        onset_component = []
        final_component = []

        if pinyin_map is not None:
            try:
                resolved_seq, onset_component, final_component = map_intermediate_syllable_to_multi_cn(
                    word_id, seq, pinyin_map
                )
                if all(phone in normalized_phone_symbols for phone in resolved_seq):
                    candidate_seq = resolved_seq
            except ValueError as exc:
                missing.add(str(exc))

        if candidate_seq is None:
            if all(phone in normalized_phone_symbols for phone in seq):
                candidate_seq = list(seq)
                onset_component = [seq[0]]
                final_component = [seq[1]]

        if candidate_seq is None:
            if pinyin_map is not None:
                try:
                    resolved_seq, _, _ = map_intermediate_syllable_to_multi_cn(word_id, seq, pinyin_map)
                    for phone in resolved_seq:
                        if phone not in normalized_phone_symbols:
                            missing.add(phone)
                except ValueError as exc:
                    missing.add(str(exc))
            else:
                for phone in seq:
                    if phone not in normalized_phone_symbols:
                        missing.add(phone)
            continue

        mapped[word_id] = candidate_seq
        components[word_id] = {"onset": onset_component, "final": final_component}

    if missing and fail_on_missing_phone:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing phones in target phones.txt: {missing_list}")
    return mapped, components, sorted(missing)


def build_nonsilence_phones(lexicon: dict[str, list[str]]) -> list[str]:
    phones = set()
    for word_id, seq in lexicon.items():
        if word_id in SPECIAL_LEXICON:
            continue
        phones.update(seq)
    return sorted(phones)


def build_extra_questions(
    intermediate_lexicon: dict[str, list[str]],
    resolved_components: dict[str, dict[str, list[str]]],
    silence_lines: list[str],
) -> list[str]:
    onset_groups: dict[str, set[str]] = defaultdict(set)
    final_groups: dict[str, set[str]] = defaultdict(set)
    tone_groups: dict[str, set[str]] = defaultdict(set)

    for word_id, seq in intermediate_lexicon.items():
        if word_id in SPECIAL_LEXICON or word_id not in resolved_components:
            continue
        onset, final = seq
        final_base_raw, _ = split_final_optional_tone(final)
        final_base = canonicalize_final_base(final_base_raw)
        tone = parse_word_tone(word_id)
        onset_groups[onset].update(resolved_components[word_id]["onset"])
        final_groups[final_base].update(resolved_components[word_id]["final"])
        if tone is not None:
            tone_groups[tone].update(resolved_components[word_id]["final"])

    lines = []
    for onset in sorted(onset_groups):
        phones = sorted(onset_groups[onset])
        if phones:
            lines.append(" ".join(phones))
    for final_base in sorted(final_groups):
        phones = sorted(final_groups[final_base])
        if phones:
            lines.append(" ".join(phones))
    for tone in sorted(tone_groups):
        phones = sorted(tone_groups[tone])
        if phones:
            lines.append(" ".join(phones))
    lines.append(" ".join(sorted(set(silence_lines))))
    return lines


def build_model_tone_questions(nonsilence_lines: list[str]) -> list[str]:
    tone_groups: dict[str, set[str]] = defaultdict(set)
    for line in nonsilence_lines:
        for phone in line.split():
            match = re.fullmatch(r".*?(\d+)$", phone)
            if match:
                tone_groups[match.group(1)].add(phone)
    lines = []
    for tone in sorted(tone_groups, key=int):
        phones = sorted(tone_groups[tone], key=tone_family_key)
        if phones:
            lines.append(" ".join(phones))
    return lines


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--items-csv",
        default="",
        help="Defaults to egs/t12_zh_pinyin/s5/config/t12_items_master.csv",
    )
    parser.add_argument("--output-dir", default="", help="Defaults to template or m11 runtime dict dir.")
    parser.add_argument(
        "--inventory-json",
        default="",
        help="Optional path for a debug inventory JSON. Defaults under output-dir.",
    )
    parser.add_argument("--m11-phones-txt", default="", help="Target M11 phones.txt for strict compatibility.")
    parser.add_argument("--model-manifest", default="", help="Optional model_manifest.json to resolve phones.txt.")
    parser.add_argument(
        "--pinyin-map",
        default="",
        help="Optional multi_cn pinyin2cmu map. Defaults to egs/multi_cn/s5/conf/pinyin2cmu when M11 phones are used.",
    )
    parser.add_argument("--fail-on-missing-phone", action="store_true")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    s5_root = script_dir.parent
    items_csv = Path(args.items_csv).resolve() if args.items_csv else s5_root / "config/t12_items_master.csv"
    manifest_path = Path(args.model_manifest).resolve() if args.model_manifest else None
    m11_phones_txt = Path(args.m11_phones_txt).resolve() if args.m11_phones_txt else None
    pinyin_map_path = Path(args.pinyin_map).resolve() if args.pinyin_map else None

    if manifest_path and not m11_phones_txt:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        phones_path_raw = manifest.get("phones_txt")
        if phones_path_raw:
            m11_phones_txt = Path(phones_path_raw).resolve()
    if m11_phones_txt and pinyin_map_path is None and DEFAULT_PINYIN_MAP.exists():
        pinyin_map_path = DEFAULT_PINYIN_MAP.resolve()

    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    elif m11_phones_txt:
        output_dir = s5_root / "runtime/dict_T12_ZH_PINYIN_m11"
    else:
        output_dir = s5_root / "runtime/dict_T12_ZH_PINYIN_template"
    inventory_json = Path(args.inventory_json).resolve() if args.inventory_json else output_dir / "inventory.json"

    items = load_items(items_csv)
    all_words = collect_all_words(items)
    intermediate_lexicon = derive_lexicon(items, all_words)
    missing_phones = []
    resolved_components = {
        word_id: {"onset": [seq[0]], "final": [seq[1]]}
        for word_id, seq in intermediate_lexicon.items()
        if word_id not in SPECIAL_LEXICON
    }
    lexicon = intermediate_lexicon
    if m11_phones_txt:
        phone_symbols = load_phone_symbols(m11_phones_txt)
        pinyin_map = load_pinyin_map(pinyin_map_path) if pinyin_map_path else None
        lexicon, resolved_components, missing_phones = map_lexicon_to_existing_phones(
            intermediate_lexicon,
            phone_symbols,
            pinyin_map,
            fail_on_missing_phone=args.fail_on_missing_phone,
        )

    lexicon_lines = [f"{word} {' '.join(lexicon[word])}" for word in sorted(lexicon)]
    lexiconp_lines = [f"{word} 1.0 {' '.join(lexicon[word])}" for word in sorted(lexicon)]
    silence_lines = []
    nonsilence_lines = []
    if m11_phones_txt:
        phone_symbols = load_phone_symbols(m11_phones_txt)
        silence_lines, nonsilence_lines = build_model_phone_inventory(phone_symbols)
    if not silence_lines:
        for key, fallback in (("!SIL", "SIL"), ("<UNK>", "SPN")):
            if key in lexicon:
                silence_lines.extend(lexicon[key])
            else:
                silence_lines.append(fallback)
        if "NSN" not in silence_lines and "nsn" not in silence_lines:
            if m11_phones_txt:
                phone_symbols = load_phone_symbols(m11_phones_txt)
                silence_lines.append(resolve_special_phone("NSN", phone_symbols))
            else:
                silence_lines.append("NSN")
    if not nonsilence_lines:
        nonsilence_lines = build_nonsilence_phones(lexicon)
    optional_silence_lines = [silence_lines[0]]
    extra_question_lines = build_extra_questions(intermediate_lexicon, resolved_components, silence_lines)
    if m11_phones_txt:
        extra_question_lines = extra_question_lines[:-1] + build_model_tone_questions(nonsilence_lines) + [
            extra_question_lines[-1]
        ]
    extra_question_lines = list(dict.fromkeys(extra_question_lines))

    write_lines(output_dir / "lexicon.txt", lexicon_lines)
    write_lines(output_dir / "lexiconp.txt", lexiconp_lines)
    write_lines(output_dir / "nonsilence_phones.txt", nonsilence_lines)
    write_lines(output_dir / "silence_phones.txt", silence_lines)
    write_lines(output_dir / "optional_silence.txt", optional_silence_lines)
    write_lines(output_dir / "extra_questions.txt", extra_question_lines)

    inventory = {
        "task_id": "T12_ZH_PINYIN",
        "items_csv": str(items_csv),
        "output_dir": str(output_dir),
        "m11_phones_txt": str(m11_phones_txt) if m11_phones_txt else None,
        "pinyin_map": str(pinyin_map_path) if pinyin_map_path else None,
        "formal_item_count": len(items),
        "lexicon_entry_count": len(all_words),
        "resolved_lexicon_entry_count": len(lexicon) - len(SPECIAL_LEXICON),
        "nonsilence_phone_count": sum(len(line.split()) for line in nonsilence_lines),
        "missing_phones": missing_phones,
        "sample_entries": {
            key: lexicon[key]
            for key in ("dao4", "dao1", "tao4", "nue3", "yue2")
            if key in lexicon
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory_json.write_text(json.dumps(inventory, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(inventory, ensure_ascii=True))


if __name__ == "__main__":
    main()
