#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
LANG_NAME="lang_t04"
MANIFEST_PATH=""
PROBE_MANIFEST_PATH=""
MODEL_DIR=""
FORCE_REBUILD=false

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
    --model-dir)
      MODEL_DIR=$2
      shift 2
      ;;
    --force-rebuild)
      FORCE_REBUILD=true
      shift
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
if [[ -z "$PROBE_MANIFEST_PATH" ]]; then
  PROBE_MANIFEST_PATH="$RUNTIME_ROOT/manifests/t04_probe_manifest.json"
fi
MODEL_DIR=$(resolve_model_dir "$RUNTIME_ROOT" "$MODEL_DIR")

LANG_DIR="$RUNTIME_ROOT/lang/$LANG_NAME"
LANG_GRAPHS_ROOT="$RUNTIME_ROOT/lang_graphs"
GRAPHS_ROOT="$RUNTIME_ROOT/graphs"
mkdir -p "$LANG_GRAPHS_ROOT" "$GRAPHS_ROOT"

ensure_dir "$LANG_DIR"
ensure_file "$LANG_DIR/words.txt"
ensure_file "$MANIFEST_PATH"

status_tsv=$(mktemp)

has_model=true
if [[ ! -f "$MODEL_DIR/final.mdl" || ! -f "$MODEL_DIR/tree" ]]; then
  has_model=false
fi

while IFS=$'\t' read -r graph_name grammar_fst; do
  ensure_file "$grammar_fst"
  lang_graph_dir="$LANG_GRAPHS_ROOT/$graph_name"
  graph_dir="$GRAPHS_ROOT/$graph_name"

  if [[ "$FORCE_REBUILD" == "true" ]]; then
    rm -rf "$lang_graph_dir" "$graph_dir"
  fi
  mkdir -p "$lang_graph_dir"
  if [[ ! -f "$lang_graph_dir/L.fst" ]]; then
    rm -rf "$lang_graph_dir"
    mkdir -p "$lang_graph_dir"
    cp -a "$LANG_DIR/." "$lang_graph_dir/"
  fi
  cp "$grammar_fst" "$lang_graph_dir/G.fst"

  if [[ "$has_model" == "true" ]]; then
    rm -rf "$graph_dir"
    (
      cd "$WSJ_S5"
      utils/mkgraph.sh "$lang_graph_dir" "$MODEL_DIR" "$graph_dir"
    )
    note="graph_built"
    graph_out="$graph_dir"
  else
    note="graph_skipped_missing_model(final.mdl/tree)"
    graph_out=""
  fi
  printf "%s\t%s\t%s\n" "$graph_name" "$graph_out" "$note" >> "$status_tsv"
done < <(
  python3 - "$MANIFEST_PATH" <<'PY'
import json, sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for e in manifest["entries"]:
    print(f'{e["graph_name"]}\t{e["grammar_fst_path"]}')
PY
)

python3 - "$MANIFEST_PATH" "$status_tsv" <<'PY'
import json, sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
status_tsv = Path(sys.argv[2])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

status_map = {}
for line in status_tsv.read_text(encoding="utf-8").splitlines():
    graph_name, graph_dir, note = line.split("\t", 2)
    status_map[graph_name] = (graph_dir, note)

for entry in manifest["entries"]:
    graph_dir, note = status_map[entry["graph_name"]]
    entry["graph_dir"] = graph_dir or None
    base_notes = entry.get("notes", "").strip()
    entry["notes"] = f"{base_notes}; build_status={note}" if base_notes else f"build_status={note}"

manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"Updated manifest with graph status: {manifest_path}")
PY

python3 - "$MANIFEST_PATH" "$PROBE_MANIFEST_PATH" "$LANG_GRAPHS_ROOT" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1]).resolve()
probe_manifest_path = Path(sys.argv[2]).resolve()
lang_graphs_root = Path(sys.argv[3]).resolve()
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

probe_entries = []
for e in manifest.get("entries", []):
    if e.get("mode") != "probe":
        continue
    graph_name = e["graph_name"]
    probe_entries.append(
        {
            "task_id": e.get("task_id"),
            "graph_name": graph_name,
            "parent_level_graph": e.get("parent_level_graph"),
            "target_word": e.get("target_word") or e.get("item_key"),
            "probe_type": e.get("probe_type"),
            "candidate_words": e.get("candidate_words", []),
            "graph_path": e.get("graph_dir"),
            "lang_graph_path": str(lang_graphs_root / graph_name),
            "diagnostic_dimension": e.get("diagnostic_dimension"),
            "diagnostic_dimension_hint": e.get("diagnostic_dimension_hint")
            or e.get("diagnostic_dimension"),
            "candidate_policy": e.get("candidate_policy"),
            "is_formal_probe": bool(e.get("is_formal_probe", False)),
            "source_set": e.get("source_set"),
            "level": e.get("level"),
        }
    )

probe_manifest = {
    "task_id": manifest.get("task_id"),
    "config": {
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
print(f"Updated probe manifest: {probe_manifest_path} ({len(probe_entries)} entries)")
PY

rm -f "$status_tsv"
echo "done: graph assets prepared under $LANG_GRAPHS_ROOT"
