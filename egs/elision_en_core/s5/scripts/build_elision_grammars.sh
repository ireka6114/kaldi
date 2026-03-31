#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
LANG_NAME="$DEFAULT_LANG_NAME"
ITEMS_JSON="$S5_ROOT/config/elision_items.json"
PROBES_JSON="$S5_ROOT/config/elision_probe_sets.json"
T02_RULES_JSON="$S5_ROOT/config/t02_dynamic_rules.json"
MANIFEST_PATH="$RUNTIME_ROOT/manifests/elision_graph_manifest.json"
PROBE_MANIFEST_PATH="$RUNTIME_ROOT/manifests/elision_probe_manifest.json"

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
    --items-json)
      ITEMS_JSON=$2
      shift 2
      ;;
    --probe-sets-json)
      PROBES_JSON=$2
      shift 2
      ;;
    --t02-rules-json)
      T02_RULES_JSON=$2
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

RUNTIME_ROOT=$(realpath "$RUNTIME_ROOT")
ITEMS_JSON=$(realpath "$ITEMS_JSON")
PROBES_JSON=$(realpath "$PROBES_JSON")
T02_RULES_JSON=$(realpath "$T02_RULES_JSON")
MANIFEST_PATH=$(realpath -m "$MANIFEST_PATH")
PROBE_MANIFEST_PATH=$(realpath -m "$PROBE_MANIFEST_PATH")

setup_kaldi_path

LANG_DIR="$RUNTIME_ROOT/lang/$LANG_NAME"
ensure_dir "$LANG_DIR"
ensure_file "$LANG_DIR/words.txt"

GRAMMAR_ROOT="$RUNTIME_ROOT/grammar"
WORD_LIST_DIR="$GRAMMAR_ROOT/word_lists"
FST_DIR="$GRAMMAR_ROOT/fsts"
mkdir -p "$WORD_LIST_DIR" "$FST_DIR" "$RUNTIME_ROOT/manifests"

python3 "$SCRIPT_DIR/generate_elision_registry.py" \
  --items-json "$ITEMS_JSON" \
  --probe-sets-json "$PROBES_JSON" \
  --t02-rules-json "$T02_RULES_JSON" \
  --words-txt "$LANG_DIR/words.txt" \
  --word-list-dir "$WORD_LIST_DIR" \
  --grammar-fst-dir "$FST_DIR" \
  --lang-dir "$LANG_DIR" \
  --manifest-path "$MANIFEST_PATH" \
  --probe-manifest-path "$PROBE_MANIFEST_PATH"

for word_list in "$WORD_LIST_DIR"/*.lst; do
  graph_name=$(basename "$word_list" .lst)
  fst_path="$FST_DIR/${graph_name}.G.fst"
  tmp_txt=$(mktemp)
  awk 'NF>0 { print "0 1 " $1 " " $1 } END { print "1" }' "$word_list" > "$tmp_txt"
  fstcompile \
    --acceptor=false \
    --isymbols="$LANG_DIR/words.txt" \
    --osymbols="$LANG_DIR/words.txt" \
    --keep_isymbols=false \
    --keep_osymbols=false \
    "$tmp_txt" | fstarcsort --sort_type=ilabel > "$fst_path"
  rm -f "$tmp_txt"
done

echo "done: grammar fst dir=$FST_DIR"
