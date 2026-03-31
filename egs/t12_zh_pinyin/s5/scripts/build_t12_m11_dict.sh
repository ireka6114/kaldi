#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
OUTPUT_DIR=""
MODEL_MANIFEST=""
M11_PHONES_TXT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      RUNTIME_ROOT=$2
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR=$2
      shift 2
      ;;
    --model-manifest)
      MODEL_MANIFEST=$2
      shift 2
      ;;
    --m11-phones-txt)
      M11_PHONES_TXT=$2
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$MODEL_MANIFEST" ]]; then
  MODEL_MANIFEST="$RUNTIME_ROOT/manifests/model_manifest.json"
fi
if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$RUNTIME_ROOT/dict_T12_ZH_PINYIN_m11"
fi

ensure_file "$MODEL_MANIFEST"

args=(
  --model-manifest "$MODEL_MANIFEST"
  --output-dir "$OUTPUT_DIR"
  --fail-on-missing-phone
)
if [[ -n "$M11_PHONES_TXT" ]]; then
  args+=(--m11-phones-txt "$M11_PHONES_TXT")
fi

python3 "$SCRIPT_DIR/generate_t12_dict_template.py" "${args[@]}"
echo "done: $OUTPUT_DIR"
