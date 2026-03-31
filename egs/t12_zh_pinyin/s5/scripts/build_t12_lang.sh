#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

DICT_DIR="$DEFAULT_DICT_DIR"
RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
LANG_NAME="lang_t12"
FORCE_REBUILD=false
PHONE_SYMBOL_TABLE=""
MODEL_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dict-dir)
      DICT_DIR=$2
      shift 2
      ;;
    --runtime-root)
      RUNTIME_ROOT=$2
      shift 2
      ;;
    --lang-name)
      LANG_NAME=$2
      shift 2
      ;;
    --phone-symbol-table)
      PHONE_SYMBOL_TABLE=$2
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
ensure_dir "$DICT_DIR"
ensure_file "$DICT_DIR/lexicon.txt"
ensure_file "$DICT_DIR/lexiconp.txt"
ensure_file "$DICT_DIR/nonsilence_phones.txt"
ensure_file "$DICT_DIR/silence_phones.txt"
ensure_file "$DICT_DIR/optional_silence.txt"
ensure_file "$DICT_DIR/extra_questions.txt"

PHONE_SYMBOL_TABLE=$(resolve_phone_symbol_table "$RUNTIME_ROOT" "$PHONE_SYMBOL_TABLE")
MODEL_DIR=$(resolve_model_dir "$RUNTIME_ROOT" "$MODEL_DIR")

LANG_ROOT="$RUNTIME_ROOT/lang"
LANG_DIR="$LANG_ROOT/$LANG_NAME"
LANG_TMP_DIR="${LANG_DIR}_tmp"
mkdir -p "$LANG_ROOT" "$RUNTIME_ROOT/manifests"

DICT_HASH_FILE="$RUNTIME_ROOT/manifests/${LANG_NAME}_dict_sha256.txt"
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

if [[ -f "$DICT_HASH_FILE" ]] && cmp -s "$TMP_HASH" "$DICT_HASH_FILE"; then
  dict_changed=false
else
  dict_changed=true
fi

if [[ "$FORCE_REBUILD" == "false" ]] \
  && [[ -f "$LANG_DIR/L.fst" ]] \
  && [[ -f "$LANG_DIR/words.txt" ]] \
  && [[ -f "$LANG_DIR/phones.txt" ]] \
  && [[ -d "$LANG_DIR/phones" ]] \
  && [[ -f "$LANG_HASH_FILE" ]] \
  && cmp -s "$TMP_HASH" "$LANG_HASH_FILE" \
  && [[ "$dict_changed" == "false" ]]; then
  echo "Lang directory already matches dict hash, skipping rebuild: $LANG_DIR"
else
  rm -rf "$LANG_DIR" "$LANG_TMP_DIR"
  (
    cd "$WSJ_S5"
    utils/validate_dict_dir.pl "$DICT_DIR"
    if [[ -n "$PHONE_SYMBOL_TABLE" ]]; then
      ensure_file "$PHONE_SYMBOL_TABLE"
      utils/prepare_lang.sh --phone-symbol-table "$PHONE_SYMBOL_TABLE" "$DICT_DIR" "<UNK>" "$LANG_TMP_DIR" "$LANG_DIR"
    else
      utils/prepare_lang.sh "$DICT_DIR" "<UNK>" "$LANG_TMP_DIR" "$LANG_DIR"
    fi
    utils/validate_lang.pl --skip-determinization-check "$LANG_DIR"
    if [[ -f "$MODEL_DIR/phones.txt" ]]; then
      utils/lang/check_phones_compatible.sh "$LANG_DIR/phones.txt" "$MODEL_DIR/phones.txt"
    elif [[ -n "$PHONE_SYMBOL_TABLE" ]]; then
      utils/lang/check_phones_compatible.sh "$LANG_DIR/phones.txt" "$PHONE_SYMBOL_TABLE"
    fi
  )
  cp "$TMP_HASH" "$LANG_HASH_FILE"
  cp "$TMP_HASH" "$DICT_HASH_FILE"
  echo "Rebuilt lang: $LANG_DIR"
fi

rm -f "$TMP_HASH"
echo "done: $LANG_DIR"
