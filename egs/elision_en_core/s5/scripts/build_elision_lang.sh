#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
ITEMS_JSON="$S5_ROOT/config/elision_items.json"
LEXICON_DELTA_TSV="$S5_ROOT/config/elision_lexicon_delta.tsv"
DICT_NAME="$DEFAULT_DICT_NAME"
LANG_NAME="$DEFAULT_LANG_NAME"
FORCE_REBUILD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      RUNTIME_ROOT=$2
      shift 2
      ;;
    --items-json)
      ITEMS_JSON=$2
      shift 2
      ;;
    --lexicon-delta-tsv)
      LEXICON_DELTA_TSV=$2
      shift 2
      ;;
    --dict-name)
      DICT_NAME=$2
      shift 2
      ;;
    --lang-name)
      LANG_NAME=$2
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
ITEMS_JSON=$(realpath "$ITEMS_JSON")
LEXICON_DELTA_TSV=$(realpath "$LEXICON_DELTA_TSV")

setup_kaldi_path
ensure_file "$ITEMS_JSON"
ensure_file "$LEXICON_DELTA_TSV"

LANG_ROOT="$RUNTIME_ROOT/lang"
DICT_DIR="$LANG_ROOT/$DICT_NAME"
LANG_DIR="$LANG_ROOT/$LANG_NAME"
LANG_TMP_DIR="${LANG_DIR}_tmp"
mkdir -p "$LANG_ROOT" "$RUNTIME_ROOT/manifests"

python3 "$SCRIPT_DIR/prepare_elision_dict.py" \
  --items-json "$ITEMS_JSON" \
  --lexicon-delta-tsv "$LEXICON_DELTA_TSV" \
  --dict-dir "$DICT_DIR"

DICT_HASH_FILE="$RUNTIME_ROOT/manifests/${DICT_NAME}_sha256.txt"
LANG_HASH_FILE="$LANG_DIR/.dict_sha256"
TMP_HASH=$(mktemp)
(
  cd "$DICT_DIR"
  sha256sum \
    extra_questions.txt \
    lexicon.txt \
    lexiconp.txt \
    nonsilence_phones.txt \
    optional_silence.txt \
    silence_phones.txt
) > "$TMP_HASH"

if [[ "$FORCE_REBUILD" == "false" ]] \
  && [[ -f "$LANG_DIR/L.fst" ]] \
  && [[ -f "$LANG_HASH_FILE" ]] \
  && cmp -s "$TMP_HASH" "$LANG_HASH_FILE"; then
  echo "Lang directory already matches dict hash, skipping rebuild: $LANG_DIR"
else
  rm -rf "$LANG_DIR" "$LANG_TMP_DIR"
  (
    cd "$WSJ_S5"
    utils/validate_dict_dir.pl "$DICT_DIR"
    utils/prepare_lang.sh "$DICT_DIR" "<UNK>" "$LANG_TMP_DIR" "$LANG_DIR"
    utils/validate_lang.pl --skip-determinization-check "$LANG_DIR"
  )
  cp "$TMP_HASH" "$LANG_HASH_FILE"
  cp "$TMP_HASH" "$DICT_HASH_FILE"
fi

rm -f "$TMP_HASH"
echo "done: $LANG_DIR"
