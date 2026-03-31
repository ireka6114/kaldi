#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
LANG_NAME="lang_t12"
MANIFEST_PATH=""
PROBE_MANIFEST_PATH=""

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
    --probe-manifest-path)
      PROBE_MANIFEST_PATH=$2
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
  MANIFEST_PATH="$RUNTIME_ROOT/manifests/t12_graph_manifest.json"
fi
if [[ -z "$PROBE_MANIFEST_PATH" ]]; then
  PROBE_MANIFEST_PATH="$RUNTIME_ROOT/manifests/t12_probe_manifest.json"
fi

LANG_DIR="$RUNTIME_ROOT/lang/$LANG_NAME"
ensure_dir "$LANG_DIR"
ensure_file "$LANG_DIR/words.txt"
ensure_file "$LANG_DIR/L.fst"
ensure_file "$LANG_DIR/phones.txt"
ensure_dir "$LANG_DIR/phones"
ensure_file "$MANIFEST_PATH"
ensure_file "$PROBE_MANIFEST_PATH"

python3 - "$MANIFEST_PATH" "$PROBE_MANIFEST_PATH" "$LANG_DIR/words.txt" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1]).resolve()
probe_manifest_path = Path(sys.argv[2]).resolve()
words_txt = Path(sys.argv[3]).resolve()

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
probe_manifest = json.loads(probe_manifest_path.read_text(encoding="utf-8"))
entries = manifest.get("entries", [])
probe_entries = probe_manifest.get("entries", [])

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
    "graph_status",
    "notes",
    "source_set",
}

if not entries:
    raise SystemExit("ERROR: manifest has no entries")

words = set()
for line in words_txt.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    words.add(line.split()[0])

level_entries = [e for e in entries if e.get("mode") == "level"]
if not level_entries:
    raise SystemExit("ERROR: no level entries found in graph manifest")

formal_entry = [e for e in level_entries if e.get("graph_name") == "T12_FORMAL"]
if not formal_entry:
    raise SystemExit("ERROR: missing required level graph T12_FORMAL")

def parse_status(entry: dict) -> str:
    if isinstance(entry.get("graph_status"), str):
        return entry["graph_status"]
    notes = entry.get("notes", "") or ""
    for part in notes.split(";"):
        token = part.strip()
        if token.startswith("build_status="):
            return token.split("=", 1)[1].strip()
    return "unknown"

for e in entries:
    missing = sorted(required_fields - set(e.keys()))
    if missing:
        raise SystemExit(f'ERROR: entry {e.get("graph_name")} missing fields: {missing}')
    cands = e["candidate_words"]
    if not isinstance(cands, list) or not cands:
        raise SystemExit(f'ERROR: entry {e.get("graph_name")} has empty candidate_words')
    if len(cands) != len(set(cands)):
        raise SystemExit(f'ERROR: entry {e.get("graph_name")} has duplicate candidate_words')
    missing_words = [w for w in cands if w not in words]
    if missing_words:
        raise SystemExit(f'ERROR: entry {e.get("graph_name")} contains words missing in words.txt: {missing_words}')

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
    dedup = []
    seen = set()
    for w in fst_words:
        if w in seen:
            continue
        seen.add(w)
        dedup.append(w)
    if set(dedup) != set(e["candidate_words"]):
        raise SystemExit(
            f"ERROR: candidate mismatch for {graph}\n"
            f"manifest={e['candidate_words']}\n"
            f"fst={dedup}"
        )
    if len(dedup) != len(e["candidate_words"]):
        raise SystemExit(
            f"ERROR: candidate cardinality mismatch for {graph}\n"
            f"manifest={len(e['candidate_words'])} fst={len(dedup)}"
        )

for e in entries:
    status = parse_status(e)
    if status == "graph_built":
        graph_dir = e.get("graph_dir")
        if not graph_dir:
            raise SystemExit(f"ERROR: graph_built but graph_dir is empty for {e['graph_name']}")
        hclg = Path(graph_dir) / "HCLG.fst"
        if not hclg.is_file():
            raise SystemExit(f"ERROR: graph_built but missing HCLG.fst: {hclg}")

formal_default_probe = [
    e
    for e in entries
    if e.get("mode") == "probe"
    and e.get("candidate_policy") == "candidate_specific_micro_probe"
    and e.get("is_formal_probe") is True
    and e.get("is_formal_default") is True
]
if not formal_default_probe:
    raise SystemExit("ERROR: no formal-default micro-probe entries found in graph manifest")

graph_by_name = {e["graph_name"]: e for e in entries}
if not probe_entries:
    raise SystemExit("ERROR: probe manifest has no entries")
for pe in probe_entries:
    name = pe.get("graph_name")
    if not name or name not in graph_by_name:
        raise SystemExit(f"ERROR: probe manifest graph missing in graph manifest: {name}")
    src = graph_by_name[name]
    if src.get("mode") != "probe":
        raise SystemExit(f"ERROR: probe manifest references non-probe graph: {name}")
    if src.get("candidate_words") != pe.get("candidate_words"):
        raise SystemExit(f"ERROR: candidate mismatch between graph/probe manifest: {name}")
    probe_graph_path = pe.get("graph_path")
    if probe_graph_path:
        hclg = Path(probe_graph_path) / "HCLG.fst"
        if not hclg.is_file():
            raise SystemExit(f"ERROR: probe graph_path missing HCLG.fst: {hclg}")

print(f"OK: manifest entries={len(entries)}")
print(f"OK: probe entries={len(probe_entries)}")
print("OK: required graph present (T12_FORMAL)")
print("OK: manifest field completeness")
print("OK: words vocabulary + grammar FST consistency")
print("OK: graph_status / graph_dir consistency")
print("OK: formal micro-probe default policy present")
print("OK: graph manifest and probe manifest are aligned")
PY

echo "done: inspect passed"
