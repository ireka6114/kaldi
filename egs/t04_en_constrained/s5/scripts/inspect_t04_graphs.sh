#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
LANG_NAME="lang_t04"
MANIFEST_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      RUNTIME_ROOT=$2
      shift 2
      ;;
    --lang-name)
      LANG_NAME=$2
      shift 2
      ;;
    --manifest-path)
      MANIFEST_PATH=$2
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

setup_kaldi_path

if [[ -z "$MANIFEST_PATH" ]]; then
  MANIFEST_PATH="$RUNTIME_ROOT/manifests/t04_graph_manifest.json"
fi

LANG_DIR="$RUNTIME_ROOT/lang/$LANG_NAME"
ensure_dir "$LANG_DIR"
ensure_file "$LANG_DIR/words.txt"
ensure_file "$LANG_DIR/L.fst"
ensure_file "$LANG_DIR/phones.txt"
ensure_dir "$LANG_DIR/phones"
ensure_file "$MANIFEST_PATH"

python3 - "$MANIFEST_PATH" "$LANG_DIR/words.txt" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1]).resolve()
words_txt = Path(sys.argv[2]).resolve()
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
entries = manifest.get("entries", [])

required_graphs = {
    "T04_CVC",
    "T04_CVCE",
    "T04_ING_A",
    "T04_ING_B",
    "T04_CVC_DEMO",
    "T04_CVCE_DEMO",
    "T04_ING_DEMO",
}
required_fields = {
    "task_id",
    "graph_name",
    "mode",
    "level",
    "item_key",
    "target_word",
    "candidate_words",
    "grammar_fst_path",
    "lang_dir",
    "graph_dir",
    "whether_formal_response",
    "is_formal_default",
    "is_formal_probe",
    "candidate_policy",
    "family_name",
    "diagnostic_dimension",
    "diagnostic_dimension_hint",
    "probe_type",
    "parent_level_graph",
    "notes",
    "source_set",
}

if not entries:
    raise SystemExit("ERROR: manifest has no entries")

present_graphs = {e["graph_name"] for e in entries}
missing_required = sorted(required_graphs - present_graphs)
if missing_required:
    raise SystemExit(f"ERROR: missing required graph names: {missing_required}")

for e in entries:
    missing = sorted(required_fields - set(e.keys()))
    if missing:
        raise SystemExit(f'ERROR: entry {e.get("graph_name")} missing fields: {missing}')
    if not isinstance(e["candidate_words"], list) or not e["candidate_words"]:
        raise SystemExit(f'ERROR: entry {e["graph_name"]} has empty candidate_words')

for e in entries:
    graph = e["graph_name"]
    fst_path = Path(e["grammar_fst_path"])
    if not fst_path.is_file():
        raise SystemExit(f"ERROR: missing grammar fst for {graph}: {fst_path}")
    cmd = [
        "fstprint",
        f"--isymbols={words_txt}",
        f"--osymbols={words_txt}",
        str(fst_path),
    ]
    out = subprocess.check_output(cmd, text=True)
    fst_words = []
    for line in out.splitlines():
        cols = line.strip().split()
        if len(cols) >= 4:
            ilabel = cols[2]
            if ilabel not in ("<eps>", "!SIL"):
                fst_words.append(ilabel)
    fst_unique = []
    seen = set()
    for w in fst_words:
        if w not in seen:
            seen.add(w)
            fst_unique.append(w)
    manifest_words = e["candidate_words"]
    if set(fst_unique) != set(manifest_words):
        raise SystemExit(
            f"ERROR: candidate mismatch for {graph}\n"
            f"manifest={manifest_words}\n"
            f"fst={fst_unique}"
        )
    if len(fst_unique) != len(manifest_words):
        raise SystemExit(
            f"ERROR: candidate cardinality mismatch for {graph}\n"
            f"manifest={len(manifest_words)} fst={len(fst_unique)}"
        )

ing_a = next(e for e in entries if e["graph_name"] == "T04_ING_A")
ing_b = next(e for e in entries if e["graph_name"] == "T04_ING_B")
if ing_a["candidate_words"] == ing_b["candidate_words"]:
    raise SystemExit("ERROR: ING_A and ING_B candidates are identical, expected separation")

formal_default = [
    e for e in entries
    if e.get("candidate_policy") == "candidate_specific_micro_probe"
    and e.get("is_formal_probe") is True
    and e.get("is_formal_default") is True
]
if not formal_default:
    raise SystemExit("ERROR: no formal-default micro-probe entries found in manifest")

family_safe_default = [
    e for e in entries
    if e.get("candidate_policy") == "item_plus_confusion_family_safe" and e.get("is_formal_default") is True
]
if family_safe_default:
    raise SystemExit("ERROR: family-safe entries must not be marked is_formal_default=true")

level_all_default = [
    e for e in entries
    if e.get("candidate_policy") == "diagnostic_level_all" and e.get("is_formal_default") is True
]
if level_all_default:
    raise SystemExit("ERROR: diagnostic level_all entries must not be marked is_formal_default=true")

print(f"OK: manifest entries={len(entries)}")
print("OK: required level/demo graphs present")
print("OK: manifest field completeness")
print("OK: grammar fst candidate consistency")
print("OK: ING_A / ING_B separation")
print("OK: micro-probe formal default policy present")
print("OK: family-safe retained as auxiliary (non-default)")
print("OK: level_all retained as diagnostic-only policy")
PY

echo "done: inspect passed"
