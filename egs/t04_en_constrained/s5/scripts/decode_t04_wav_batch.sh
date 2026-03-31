#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
GRAPH_NAME="T04_CVC"
WAV_DIR=""
MODEL_DIR=""
MAX_WAVS=12
OUT_JSON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      RUNTIME_ROOT=$2
      shift 2
      ;;
    --graph-name)
      GRAPH_NAME=$2
      shift 2
      ;;
    --wav-dir)
      WAV_DIR=$2
      shift 2
      ;;
    --model-dir)
      MODEL_DIR=$2
      shift 2
      ;;
    --max-wavs)
      MAX_WAVS=$2
      shift 2
      ;;
    --output-json)
      OUT_JSON=$2
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

setup_kaldi_path

if [[ -z "$WAV_DIR" ]]; then
  echo "ERROR: --wav-dir is required" >&2
  exit 1
fi
if [[ -z "$OUT_JSON" ]]; then
  OUT_JSON="$RUNTIME_ROOT/manifests/t04_batch_decode_${GRAPH_NAME}.json"
fi

ensure_dir "$WAV_DIR"
MODEL_DIR=$(resolve_model_dir "$RUNTIME_ROOT" "$MODEL_DIR")

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

wav_list="$tmp_dir/wavs.txt"
find "$WAV_DIR" -maxdepth 1 -type f -name '*.wav' | sort | head -n "$MAX_WAVS" > "$wav_list"

if [[ ! -s "$wav_list" ]]; then
  echo "ERROR: no wav files found under $WAV_DIR" >&2
  exit 1
fi

mkdir -p "$RUNTIME_ROOT/manifests"
result_list="$tmp_dir/results.txt"

while IFS= read -r wav; do
  base=$(basename "$wav" .wav)
  out_json="$RUNTIME_ROOT/manifests/t04_decode_${GRAPH_NAME}_${base}.json"
  "$SCRIPT_DIR/smoke_test_t04_decode.sh" \
    --runtime-root "$RUNTIME_ROOT" \
    --graph-name "$GRAPH_NAME" \
    --audio-path "$wav" \
    --model-dir "$MODEL_DIR" \
    --output-json "$out_json"
  echo "$out_json" >> "$result_list"
done < "$wav_list"

python3 - "$OUT_JSON" "$GRAPH_NAME" "$result_list" <<'PY'
import json
import sys
from pathlib import Path

out_path = Path(sys.argv[1])
graph_name = sys.argv[2]
result_paths = [Path(x.strip()) for x in Path(sys.argv[3]).read_text(encoding="utf-8").splitlines() if x.strip()]
results = [json.loads(p.read_text(encoding="utf-8")) for p in result_paths]
summary = {
    "graph_name": graph_name,
    "num_wavs": len(results),
    "results": results,
}
out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"Wrote batch decode summary: {out_path}")
PY
