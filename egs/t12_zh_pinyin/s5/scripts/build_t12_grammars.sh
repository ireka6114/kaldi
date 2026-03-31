#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
LANG_NAME="lang_t12"
CONFIG_JSON="$S5_ROOT/config/t12_word_sets.json"
CONFUSION_CONFIG_JSON="$S5_ROOT/config/t12_confusion_sets.json"
ITEMS_CSV="$S5_ROOT/config/t12_items_master.csv"
MANIFEST_PATH=""
PROBE_MANIFEST_PATH=""
INCLUDE_ITEM_AWARE=false

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
    --config-json)
      CONFIG_JSON=$2
      shift 2
      ;;
    --confusion-config-json)
      CONFUSION_CONFIG_JSON=$2
      shift 2
      ;;
    --items-csv)
      ITEMS_CSV=$2
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
    --include-item-aware)
      INCLUDE_ITEM_AWARE=true
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

setup_kaldi_path
ensure_file "$CONFIG_JSON"
ensure_file "$CONFUSION_CONFIG_JSON"
ensure_file "$ITEMS_CSV"

LANG_DIR="$RUNTIME_ROOT/lang/$LANG_NAME"
ensure_dir "$LANG_DIR"
ensure_file "$LANG_DIR/words.txt"

GRAMMAR_ROOT="$RUNTIME_ROOT/grammar"
WORD_LIST_DIR="$GRAMMAR_ROOT/word_lists"
FST_DIR="$GRAMMAR_ROOT/fsts"
mkdir -p "$WORD_LIST_DIR" "$FST_DIR" "$RUNTIME_ROOT/manifests"

if [[ -z "$MANIFEST_PATH" ]]; then
  MANIFEST_PATH="$RUNTIME_ROOT/manifests/t12_graph_manifest.json"
fi
if [[ -z "$PROBE_MANIFEST_PATH" ]]; then
  PROBE_MANIFEST_PATH="$RUNTIME_ROOT/manifests/t12_probe_manifest.json"
fi

PY_ARGS=(
  --config-json "$CONFIG_JSON"
  --confusion-config-json "$CONFUSION_CONFIG_JSON"
  --items-csv "$ITEMS_CSV"
  --words-txt "$LANG_DIR/words.txt"
  --word-list-dir "$WORD_LIST_DIR"
  --grammar-fst-dir "$FST_DIR"
  --lang-dir "$LANG_DIR"
  --manifest-path "$MANIFEST_PATH"
  --probe-manifest-path "$PROBE_MANIFEST_PATH"
)
if [[ "$INCLUDE_ITEM_AWARE" == "true" ]]; then
  PY_ARGS+=(--include-item-aware)
fi
"$SCRIPT_DIR/t12_generate_registry.py" "${PY_ARGS[@]}"

compile_one_fst() {
  local word_list=$1
  local fst_path=$2
  local tmp_txt
  tmp_txt=$(mktemp)

  awk 'NF>0 { print "0 1 " $1 " " $1 } END { print "1" }' "$word_list" > "$tmp_txt"

  fstcompile \
    --acceptor=false \
    --isymbols="$LANG_DIR/words.txt" \
    --osymbols="$LANG_DIR/words.txt" \
    --keep_isymbols=false \
    --keep_osymbols=false \
    "$tmp_txt" \
    | fstarcsort --sort_type=ilabel > "$fst_path"

  rm -f "$tmp_txt"
}

for word_list in "$WORD_LIST_DIR"/*.lst; do
  graph_name=$(basename "$word_list" .lst)
  fst_path="$FST_DIR/${graph_name}.G.fst"
  compile_one_fst "$word_list" "$fst_path"
done

echo "done: grammar fst dir=$FST_DIR"
echo "done: manifest=$MANIFEST_PATH"
echo "done: probe_manifest=$PROBE_MANIFEST_PATH"
