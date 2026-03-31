#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
LANG_NAME="$DEFAULT_LANG_NAME"
MANIFEST_PATH="$RUNTIME_ROOT/manifests/elision_graph_manifest.json"
PROBE_MANIFEST_PATH="$RUNTIME_ROOT/manifests/elision_probe_manifest.json"
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

RUNTIME_ROOT=$(realpath "$RUNTIME_ROOT")
MANIFEST_PATH=$(realpath "$MANIFEST_PATH")
PROBE_MANIFEST_PATH=$(realpath "$PROBE_MANIFEST_PATH")

setup_kaldi_path
MODEL_DIR=$(resolve_model_dir "$RUNTIME_ROOT" "$MODEL_DIR")

LANG_DIR="$RUNTIME_ROOT/lang/$LANG_NAME"
LANG_GRAPHS_ROOT="$RUNTIME_ROOT/lang_graphs"
GRAPHS_ROOT="$RUNTIME_ROOT/graphs"
mkdir -p "$LANG_GRAPHS_ROOT" "$GRAPHS_ROOT" "$RUNTIME_ROOT/manifests"

ensure_dir "$LANG_DIR"
ensure_file "$MANIFEST_PATH"

status_tsv=$(mktemp)
while IFS=$'\t' read -r graph_name grammar_fst; do
  lang_graph_dir="$LANG_GRAPHS_ROOT/$graph_name"
  graph_dir="$GRAPHS_ROOT/$graph_name"
  if [[ "$FORCE_REBUILD" == "true" ]]; then
    rm -rf "$lang_graph_dir" "$graph_dir"
  fi
  rm -rf "$lang_graph_dir"
  mkdir -p "$lang_graph_dir"
  cp -a "$LANG_DIR/." "$lang_graph_dir/"
  cp "$grammar_fst" "$lang_graph_dir/G.fst"
  rm -rf "$graph_dir"
  (
    cd "$WSJ_S5"
    utils/mkgraph.sh "$lang_graph_dir" "$MODEL_DIR" "$graph_dir"
  )
  printf "%s\t%s\t%s\n" "$graph_name" "$graph_dir" "$lang_graph_dir" >> "$status_tsv"
done < <(
  python3 - "$MANIFEST_PATH" <<'PY'
import json, sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for e in manifest["entries"]:
    print(f'{e["graph_name"]}\t{e["grammar_fst_path"]}')
PY
)

python3 - "$MANIFEST_PATH" "$PROBE_MANIFEST_PATH" "$status_tsv" "$MODEL_DIR" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
probe_manifest_path = Path(sys.argv[2])
status_tsv = Path(sys.argv[3])
model_dir = Path(sys.argv[4]).resolve()

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
probe_manifest = json.loads(probe_manifest_path.read_text(encoding="utf-8"))
status = {}
for line in status_tsv.read_text(encoding="utf-8").splitlines():
    graph_name, graph_dir, lang_graph_dir = line.split("\t")
    status[graph_name] = {"graph_dir": graph_dir, "lang_graph_path": lang_graph_dir}

for entry in manifest["entries"]:
    entry.update(status[entry["graph_name"]])
for entry in probe_manifest["entries"]:
    entry.update(status[entry["graph_name"]])

manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
probe_manifest_path.write_text(json.dumps(probe_manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

model_manifest = {
    "task_id": manifest["task_id"],
    "core_name": "ELISION_EN_CORE",
    "applicable_tasks": ["T01_EN", "T02_EN"],
    "task_mode": "shared_core",
    "model_dir": str(model_dir),
    "model_type": "shared_english_am"
}
model_manifest_path = manifest_path.parent / "elision_model_manifest.json"
env_path = manifest_path.parent / "model_paths.env"
model_manifest_path.write_text(json.dumps(model_manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
env_path.write_text(f"ELISION_EN_MODEL_DIR={model_dir}\n", encoding="utf-8")
PY

rm -f "$status_tsv"
echo "done: graph assets prepared under $GRAPHS_ROOT"
