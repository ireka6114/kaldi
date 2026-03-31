#!/usr/bin/env python3

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import yaml

VOWELS = set("aeiouy")
PHONE_VOWELS = {"O_SHORT_I", "O_LONG_I", "IH_I", "AE", "AH", "AA", "EH", "IY", "UW", "AY", "OW", "AO"}

# Compact, local, reproducible reference lexicon for word-likeness proxies.
REFERENCE_REAL_WORDS = {
    "bad","bag","ban","bat","bed","beg","bet","bid","big","bin","bit","bob","bog","bot","bud","bug","bun","bus","but",
    "cab","can","cap","cat","cod","cog","cop","cot","cub","cut","dad","dam","den","did","dig","dim","dip","dog","dot",
    "fan","fat","fed","fig","fin","fit","fog","fop","fox","fun","fur","gap","gas","get","gig","gin","got","gum","gun",
    "had","ham","hen","hid","hip","hit","hog","hop","hot","hug","hut","jab","jam","jet","jig","job","jog","jot","jug",
    "kid","kit","lab","lag","lap","let","lid","lip","lit","log","lot","mad","map","mat","men","met","mix","mob","mop",
    "mud","mug","nab","net","nip","nod","not","nut","pad","pan","pat","peg","pen","pet","pig","pin","pit","pod","pop",
    "pot","pub","pug","pun","rag","ram","ran","rap","rat","red","rig","rim","rip","rod","rot","rug","run","sad","sag",
    "sap","sat","set","sip","sit","sob","sod","sop","sot","sun","tab","tag","tap","tar","ten","tip","top","tot","tub",
    "van","vat","vet","wig","win","wit","wok","zap","zig","zip","zit","cape","coke","cone","cope","cute","dame","dine",
    "dope","dote","fake","fame","fate","fine","fire","gate","game","gape","gope","hope","hote","jape","joke","kite","late",
    "like","line","lote","made","mate","mote","name","nope","note","pace","pane","pine","pipe","pope","rate","ripe","robe",
    "rope","rote","same","sane","site","tape","time","tone","tope","tube","vape","vote","wade","wave","wine","wipe","zone"
}

ONSET_MAP = {
    "b": "B", "d": "D", "f": "F", "g": "G", "j": "JH", "k": "K", "l": "L", "m": "M", "n": "N", "p": "P", "r": "R",
    "s": "S", "t": "T", "v": "V", "w": "W", "z": "Z", "h": "HH", "y": "Y"
}
CODA_MAP = {"p": "P", "t": "T", "d": "D", "b": "B", "k": "K", "g": "G"}


def parse_pair(s: str) -> tuple[str, str] | None:
    if ":" in s:
        a, b = s.split(":", 1)
    elif "/" in s:
        a, b = s.split("/", 1)
    else:
        return None
    a = a.strip()
    b = b.strip()
    if not a or not b or a == b:
        return None
    return a, b


def levenshtein(a: str | list[str], b: str | list[str]) -> int:
    aa = list(a)
    bb = list(b)
    if len(aa) < len(bb):
        aa, bb = bb, aa
    prev = list(range(len(bb) + 1))
    for i, ca in enumerate(aa, 1):
        cur = [i]
        for j, cb in enumerate(bb, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (0 if ca == cb else 1)))
        prev = cur
    return prev[-1]


def parse_align_lexicon(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.strip().split()
        if len(cols) >= 3:
            out[cols[1]] = cols[2:]
    return out


def load_t04_inventory(word_sets_path: Path) -> dict:
    conf = json.loads(word_sets_path.read_text(encoding="utf-8"))
    formal = conf["formal_levels"]
    inventory = {}
    for level_key, info in formal.items():
        for w in info.get("words", []):
            inventory[w] = {
                "level_key": level_key,
                "source_set": info.get("source_set"),
                "level_tag": info.get("level_tag"),
            }
    return inventory


def infer_template(word: str, phones: list[str]) -> str:
    if word.endswith("ing"):
        return "ING_SHORT" if "O_SHORT_I" in phones else "ING_LONG"
    if word.endswith("e"):
        return "CVCE"
    return "CVC"


def extract_structure(word: str, phones: list[str]) -> dict:
    onset = None
    nucleus = None
    coda = None
    for i, p in enumerate(phones):
        if p in {"O_SHORT_I", "O_LONG_I"} and nucleus is None:
            nucleus = p
            onset = phones[i - 1] if i > 0 else None
            coda = phones[i + 1] if i + 1 < len(phones) else None
            break
    if nucleus is None:
        for i, p in enumerate(phones):
            if p in PHONE_VOWELS:
                nucleus = p
                onset = phones[i - 1] if i > 0 else None
                coda = phones[i + 1] if i + 1 < len(phones) else None
                break
    return {
        "onset_phone": onset,
        "nucleus_phone": nucleus,
        "coda_phone": coda,
        "grapheme_onset": word[0] if word else "",
        "grapheme_nucleus": "o" if "o" in word else next((c for c in word if c in VOWELS), ""),
        "grapheme_coda": word[-1] if word else "",
    }


def legality_flags(word: str, forbidden_bigrams: list[str]) -> dict:
    flags = []
    if not word.isascii() or not word.islower():
        flags.append("non_ascii_or_non_lower")
    if sum(1 for c in word if c in VOWELS) < 1:
        flags.append("no_vowel")
    for bg in forbidden_bigrams:
        if bg in word:
            flags.append(f"forbidden_bigram:{bg}")
    # Simple pronounceability heuristic: disallow 4+ consonant run.
    run = 0
    max_run = 0
    for c in word:
        if c in VOWELS:
            run = 0
        else:
            run += 1
            max_run = max(max_run, run)
    if max_run >= 4:
        flags.append("long_consonant_cluster")
    return {
        "orthographic_flags": flags,
        "orthographic_legal": len(flags) == 0,
    }


def build_char_lm(words: set[str]) -> dict:
    tri = Counter()
    bi = Counter()
    chars = sorted(set("".join(words)) | {"^", "$"})
    for w in words:
        s = f"^{w}$"
        for i in range(len(s) - 2):
            bi[s[i : i + 2]] += 1
            tri[s[i : i + 3]] += 1
    return {"tri": tri, "bi": bi, "vocab_size": len(chars)}


def trigram_score(word: str, lm: dict) -> float:
    tri = lm["tri"]
    bi = lm["bi"]
    v = lm["vocab_size"]
    s = f"^{word}$"
    vals = []
    for i in range(len(s) - 2):
        b = s[i : i + 2]
        t = s[i : i + 3]
        p = (tri.get(t, 0) + 1.0) / (bi.get(b, 0) + v)
        vals.append(math.log(p))
    return sum(vals) / len(vals) if vals else -99.0


def pseudo_phone_tokens(word: str, long_vowel: bool | None = None) -> list[str]:
    if word.endswith("ing"):
        stem = word[:-3]
    else:
        stem = word

    if long_vowel is None:
        long_vowel = stem.endswith("e") and len(stem) >= 3

    base = stem[:-1] if (len(stem) >= 3 and stem.endswith("e")) else stem
    onset = base[0] if base else ""
    coda = base[-1] if len(base) >= 2 else ""
    onset_phone = ONSET_MAP.get(onset, onset.upper())
    coda_phone = CODA_MAP.get(coda, coda.upper())
    v = "O_LONG_I" if long_vowel else "O_SHORT_I"
    out = [f"{onset_phone}_B", v, f"{coda_phone}_E"] if onset and coda else [v]
    if word.endswith("ing"):
        # Approximate T04 doubling logic.
        out = [f"{onset_phone}_B", v, f"{coda_phone}_I", "IH_I", "NG_E"] if onset and coda else [v, "IH_I", "NG_E"]
    return out


def nearest_real_words(word: str, real_words: set[str], topk: int = 3) -> list[dict]:
    scored = sorted(((rw, levenshtein(word, rw)) for rw in real_words), key=lambda x: (x[1], x[0]))
    return [{"word": w, "distance": d} for w, d in scored[:topk]]


def neighborhood_counts(word: str, peers: list[str], real_words: set[str]) -> dict:
    pseudo_n1 = sum(1 for w in peers if w != word and levenshtein(word, w) == 1)
    real_n1 = sum(1 for w in real_words if levenshtein(word, w) == 1)
    nearest = nearest_real_words(word, real_words, topk=3)
    return {
        "orthographic_pseudo_neighbors_1edit": pseudo_n1,
        "orthographic_real_neighbors_1edit": real_n1,
        "nearest_real_words": nearest,
        "nearest_real_distance": nearest[0]["distance"] if nearest else None,
    }


def phone_neighborhood(word: str, phone_map: dict[str, list[str]], peers: list[str], real_phone_map: dict[str, list[str]]) -> dict:
    p = phone_map[word]
    pseudo_n1 = sum(1 for w in peers if w != word and levenshtein(p, phone_map[w]) == 1)
    real_d = sorted(((rw, levenshtein(p, rp)) for rw, rp in real_phone_map.items()), key=lambda x: (x[1], x[0]))
    real_n1 = sum(1 for _w, d in real_d if d == 1)
    top = [{"word": w, "distance": d} for w, d in real_d[:3]]
    return {
        "phonological_pseudo_neighbors_1edit": pseudo_n1,
        "phonological_real_neighbors_1edit": real_n1,
        "nearest_real_words_phonological": top,
        "nearest_real_phone_distance": top[0]["distance"] if top else None,
    }


def build_minpair_graph(words: list[str]) -> dict[str, set[str]]:
    g = {w: set() for w in words}
    for i, a in enumerate(words):
        for b in words[i + 1 :]:
            if len(a) == len(b) and levenshtein(a, b) == 1:
                g[a].add(b)
                g[b].add(a)
    return g


def connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    seen = set()
    out = []
    for n in graph:
        if n in seen:
            continue
        stack = [n]
        comp = []
        seen.add(n)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in graph[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        out.append(sorted(comp))
    return out


def percentile(value: float, values: list[float]) -> float:
    if not values:
        return 0.0
    le = sum(1 for v in values if v <= value)
    return le / len(values)


def evaluate_inventory(rules: dict, inventory: dict, lex: dict) -> tuple[dict, dict]:
    words = sorted(inventory.keys())
    real_words = set(REFERENCE_REAL_WORDS)
    lm = build_char_lm(real_words)

    phone_map = {}
    for w in words:
        phone_map[w] = lex.get(w, pseudo_phone_tokens(w, long_vowel=(w.endswith("e") and not w.endswith("ing"))))

    real_phone_map = {w: pseudo_phone_tokens(w, long_vowel=w.endswith("e")) for w in real_words}

    graph = build_minpair_graph(words)
    comps = connected_components(graph)
    comp_index = {}
    for i, comp in enumerate(comps):
        for w in comp:
            comp_index[w] = i

    scores = {w: trigram_score(w, lm) for w in words}
    score_values = list(scores.values())

    fixed_pairs = [p for p in (parse_pair(x) for x in rules["audit_targets"]["fixed_am_indistinguishable_pairs"]) if p]
    control_pairs = [p for p in (parse_pair(x) for x in rules["audit_targets"]["control_separable_pairs"]) if p]
    fixed_words = {x for p in fixed_pairs for x in p}
    control_words = {x for p in control_pairs for x in p}

    items = {}
    for w in words:
        phones = phone_map[w]
        tmpl = infer_template(w, phones)
        struct = extract_structure(w, phones)
        legal = legality_flags(w, rules["orthographic_legality"]["forbidden_bigrams"])
        neigh = neighborhood_counts(w, words, real_words)
        pneigh = phone_neighborhood(w, phone_map, words, real_phone_map)

        in_fixed = w in fixed_words
        in_control = w in control_words
        csize = len(comps[comp_index[w]])
        degree = len(graph[w])

        over_wordlike = (
            (neigh["nearest_real_distance"] is not None and neigh["nearest_real_distance"] <= 1)
            and neigh["orthographic_real_neighbors_1edit"] >= 2
            and percentile(scores[w], score_values) >= 0.75
        )
        too_alien = (
            (neigh["nearest_real_distance"] is not None and neigh["nearest_real_distance"] >= 3)
            and neigh["orthographic_real_neighbors_1edit"] == 0
            and percentile(scores[w], score_values) <= 0.2
        )

        items[w] = {
            "template_type": tmpl,
            "grapheme_length": len(w),
            "phoneme_length": len(phones),
            "onset_nucleus_coda": struct,
            "phoneme_sequence": phones,
            "orthographic_legality": legal,
            "phonotactic_probability_proxy": {
                "char_trigram_avg_logprob": scores[w],
                "percentile_within_inventory": percentile(scores[w], score_values),
            },
            "orthographic_neighborhood": neigh,
            "phonological_neighborhood": pneigh,
            "minimal_pair_cluster": {
                "cluster_id": comp_index[w],
                "cluster_size": csize,
                "degree": degree,
            },
            "belongs_to_known_am_indistinguishable_pair": in_fixed,
            "belongs_to_known_control_separable_pair": in_control,
            "risk_flags": {
                "likely_over_wordlike": over_wordlike,
                "likely_too_alien": too_alien,
                "high_minpair_burden": csize > rules["minimal_pair_burden"]["max_cluster_size"] or degree > rules["minimal_pair_burden"]["max_degree_in_minpair_graph"],
            },
        }

    templates = Counter(items[w]["template_type"] for w in items)
    tvals = list(templates.values())
    template_ratio = (max(tvals) / min(tvals)) if tvals and min(tvals) > 0 else None

    problematic_stats = [items[w] for w in words if w in fixed_words]
    other_stats = [items[w] for w in words if w not in fixed_words]

    def mean(xs: list[float | int | None]) -> float | None:
        ys = [float(x) for x in xs if x is not None]
        return (sum(ys) / len(ys)) if ys else None

    findings = {
        "over_wordlike_items": sorted([w for w, v in items.items() if v["risk_flags"]["likely_over_wordlike"]]),
        "too_alien_items": sorted([w for w, v in items.items() if v["risk_flags"]["likely_too_alien"]]),
        "high_burden_clusters": [
            {"cluster_id": i, "items": comp, "size": len(comp)}
            for i, comp in enumerate(comps)
            if len(comp) > rules["minimal_pair_burden"]["max_cluster_size"]
        ],
        "template_balance": {
            "counts": dict(templates),
            "max_to_min_ratio": template_ratio,
            "passes_balance_rule": (template_ratio is not None and template_ratio <= rules["template_balance"]["max_template_ratio"]),
        },
        "problematic_pair_correlation": {
            "problem_words": sorted(fixed_words),
            "control_words": sorted(control_words),
            "problem_vs_other_mean_orth_real_n1": {
                "problem": mean([x["orthographic_neighborhood"]["orthographic_real_neighbors_1edit"] for x in problematic_stats]),
                "other": mean([x["orthographic_neighborhood"]["orthographic_real_neighbors_1edit"] for x in other_stats]),
            },
            "problem_vs_other_mean_phonotactic_percentile": {
                "problem": mean([x["phonotactic_probability_proxy"]["percentile_within_inventory"] for x in problematic_stats]),
                "other": mean([x["phonotactic_probability_proxy"]["percentile_within_inventory"] for x in other_stats]),
            },
            "problematic_pairs_isolated_or_broader": "isolated_or_mixed",
        },
    }

    if findings["problematic_pair_correlation"]["problem_vs_other_mean_orth_real_n1"]["problem"] is not None:
        p = findings["problematic_pair_correlation"]["problem_vs_other_mean_orth_real_n1"]["problem"]
        o = findings["problematic_pair_correlation"]["problem_vs_other_mean_orth_real_n1"]["other"]
        findings["problematic_pair_correlation"]["problematic_pairs_isolated_or_broader"] = (
            "correlated_with_broader_wordlikeness" if (o is not None and p > o) else "pair_specific_or_weakly_correlated"
        )

    return items, findings


def candidate_record(stem: str, existing_words: set[str], real_words: set[str], lm: dict, rules: dict) -> dict:
    short = stem
    long = f"{stem}e"
    s_ing_short = f"{stem}{stem[-1]}ing"
    s_ing_long = f"{stem}ing"

    words = [short, long, s_ing_short, s_ing_long]
    reasons = []
    if any(w in existing_words for w in words):
        reasons.append("collides_with_existing_production_item")

    nearest_short = nearest_real_words(short, real_words, topk=1)
    nearest_long = nearest_real_words(long, real_words, topk=1)
    d_short = nearest_short[0]["distance"] if nearest_short else 99
    d_long = nearest_long[0]["distance"] if nearest_long else 99
    if short in real_words or long in real_words:
        reasons.append("exact_real_word_match")
    min_d = min(d_short, d_long)
    if min_d < rules["real_word_similarity"]["min_orthographic_distance_to_real_word"]:
        reasons.append("too_close_to_real_word")

    score_short = trigram_score(short, lm)
    score_long = trigram_score(long, lm)

    if not short.islower() or not short.isascii():
        reasons.append("orthographic_illegal")

    accepted = len(reasons) == 0
    return {
        "stem": stem,
        "short_word": short,
        "long_word": long,
        "ing_short_word": s_ing_short,
        "ing_long_word": s_ing_long,
        "nearest_real_short": nearest_short,
        "nearest_real_long": nearest_long,
        "char_trigram_score_short": score_short,
        "char_trigram_score_long": score_long,
        "retained": accepted,
        "reasons": reasons,
    }


def control_anchor_record(short_word: str, long_word: str, real_words: set[str], lm: dict) -> dict:
    stem = short_word
    return {
        "stem": stem,
        "short_word": short_word,
        "long_word": long_word,
        "ing_short_word": f"{stem}{stem[-1]}ing",
        "ing_long_word": f"{stem}ing",
        "nearest_real_short": nearest_real_words(short_word, real_words, topk=1),
        "nearest_real_long": nearest_real_words(long_word, real_words, topk=1),
        "char_trigram_score_short": trigram_score(short_word, lm),
        "char_trigram_score_long": trigram_score(long_word, lm),
        "retained": True,
        "reasons": ["existing_control_anchor"],
        "source_pair": f"{short_word}:{long_word}",
    }


def generate_candidate_pool(rules: dict, findings: dict, inventory_words: set[str]) -> dict:
    fixed_pairs = [p for p in (parse_pair(x) for x in rules["audit_targets"]["fixed_am_indistinguishable_pairs"]) if p]
    control_pairs = [p for p in (parse_pair(x) for x in rules["audit_targets"]["control_separable_pairs"]) if p]

    allowed_onsets = list(rules["candidate_generation"]["allowed_onsets"])
    blocked_onsets = set(rules["candidate_generation"]["avoid_onsets_for_problem_replacement"])
    allowed_codas = list(rules["candidate_generation"]["allowed_codas"])
    per_pair = int(rules["candidate_generation"]["replacement_per_problem_pair"])
    pilot_k = int(rules["candidate_generation"]["suggested_pilot_replacements_per_pair"])

    real_words = set(REFERENCE_REAL_WORDS)
    lm = build_char_lm(real_words)

    out = {
        "fixed_pair_replacements": {},
        "control_matched_candidates": {"accepted": [], "rejected": []},
        "suggested_pilot_set": {"replacements": [], "controls": []},
    }
    pilot_used_stems = set()

    for a, b in fixed_pairs:
        coda_hint = a[-1]
        codas = [coda_hint] if coda_hint in allowed_codas else allowed_codas
        pool = []
        for o in allowed_onsets:
            if o in blocked_onsets:
                continue
            for c in codas:
                stem = f"{o}o{c}"
                rec = candidate_record(stem, inventory_words, real_words, lm, rules)
                rec["source_pair"] = f"{a}:{b}"
                if rec["retained"]:
                    rec["score"] = (rec["nearest_real_short"][0]["distance"] if rec["nearest_real_short"] else 3) + (
                        rec["nearest_real_long"][0]["distance"] if rec["nearest_real_long"] else 3
                    )
                pool.append(rec)

        accepted = sorted([x for x in pool if x["retained"]], key=lambda x: (-x["score"], x["stem"]))[:per_pair]
        rejected = [x for x in pool if not x["retained"]][: per_pair * 2]
        out["fixed_pair_replacements"][f"{a}:{b}"] = {"accepted": accepted, "rejected": rejected}
        picked = []
        for rec in accepted:
            if rec["stem"] in pilot_used_stems:
                continue
            picked.append(rec)
            pilot_used_stems.add(rec["stem"])
            if len(picked) >= pilot_k:
                break
        if not picked and accepted:
            picked = accepted[:1]
        out["suggested_pilot_set"]["replacements"].extend(picked)

    # Control matched candidates: keep existing controls as anchors.
    for a, b in control_pairs:
        short_word, long_word = (a, b) if len(a) <= len(b) else (b, a)
        anchor = control_anchor_record(short_word, long_word, real_words, lm)
        out["control_matched_candidates"]["accepted"].append(anchor)
        out["suggested_pilot_set"]["controls"].append(anchor)

    return out


def write_markdown(path: Path, findings: dict, items: dict, candidate_pool: dict) -> None:
    lines = [
        "# T04 Pseudoword Theory Audit",
        "",
        "This audit treats T04 as a stimulus-design problem (not scorer heuristics).",
        "",
        "## Key Findings",
        f"- likely over-wordlike items: `{', '.join(findings['over_wordlike_items']) or '(none)'}`",
        f"- likely too sparse/alien items: `{', '.join(findings['too_alien_items']) or '(none)'}`",
        f"- problematic pair pattern: `{findings['problematic_pair_correlation']['problematic_pairs_isolated_or_broader']}`",
        f"- template counts: `{findings['template_balance']['counts']}`",
        f"- template max/min ratio: `{findings['template_balance']['max_to_min_ratio']}`",
        "",
        "## High-Burden Minimal-Pair Clusters",
    ]
    if findings["high_burden_clusters"]:
        for c in findings["high_burden_clusters"]:
            lines.append(f"- cluster {c['cluster_id']} size={c['size']}: `{', '.join(c['items'])}`")
    else:
        lines.append("- none above rule threshold")

    lines.extend([
        "",
        "## Candidate Redesign Summary",
    ])
    for pair, data in candidate_pool["fixed_pair_replacements"].items():
        lines.append(f"### {pair}")
        lines.append(f"- accepted: `{', '.join(x['short_word'] + '/' + x['long_word'] for x in data['accepted']) or '(none)'}`")
        lines.append(f"- rejected_count: `{len(data['rejected'])}`")

    lines.extend([
        "",
        "## Suggested Pilot Set",
        f"- replacements: `{', '.join(x['short_word'] + '/' + x['long_word'] for x in candidate_pool['suggested_pilot_set']['replacements']) or '(none)'}`",
        f"- controls: `{', '.join(x['short_word'] + '/' + x['long_word'] for x in candidate_pool['suggested_pilot_set']['controls']) or '(none)'}`",
        "",
    ])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Theory-driven audit and redesign scaffold for T04 pseudowords.")
    ap.add_argument("--word-sets", default="egs/t04_en_constrained/s5/config/t04_word_sets.json")
    ap.add_argument("--align-lexicon", default="egs/t04_en_constrained/s5/runtime/lang/lang_t04/phones/align_lexicon.txt")
    ap.add_argument("--rules-yaml", default="egs/t04_en_constrained/s5/experiments/t04_stimulus_redesign/config/t04_redesign_rules.yaml")
    ap.add_argument("--output-json", default="egs/t04_en_constrained/s5/experiments/t04_stimulus_redesign/reports/t04_pseudoword_theory_audit_report.json")
    ap.add_argument("--output-md", default="egs/t04_en_constrained/s5/experiments/t04_stimulus_redesign/docs/t04_pseudoword_theory_audit.md")
    ap.add_argument("--candidate-pool-json", default="egs/t04_en_constrained/s5/experiments/t04_stimulus_redesign/candidates/t04_redesigned_candidate_pool.json")
    args = ap.parse_args()

    rules = yaml.safe_load(Path(args.rules_yaml).read_text(encoding="utf-8"))
    inventory = load_t04_inventory(Path(args.word_sets))
    lex = parse_align_lexicon(Path(args.align_lexicon))

    items, findings = evaluate_inventory(rules, inventory, lex)
    candidate_pool = generate_candidate_pool(rules, findings, set(inventory.keys()))

    report = {
        "rules_version": rules.get("version"),
        "inventory_size": len(items),
        "items": items,
        "findings": findings,
    }

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    cand_json = Path(args.candidate_pool_json)
    cand_json.parent.mkdir(parents=True, exist_ok=True)
    cand_json.write_text(json.dumps(candidate_pool, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    write_markdown(Path(args.output_md), findings, items, candidate_pool)

    print(f"wrote audit json: {out_json}")
    print(f"wrote audit markdown: {args.output_md}")
    print(f"wrote candidate pool: {cand_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
