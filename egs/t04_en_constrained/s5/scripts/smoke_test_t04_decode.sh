#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
MANIFEST_PATH=""
GRAPH_NAME="T04_CVC"
AUDIO_PATH=""
MODEL_DIR=""
MFCC_CONFIG=""
OUTPUT_JSON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      RUNTIME_ROOT=$2
      shift 2
      ;;
    --manifest-path)
      MANIFEST_PATH=$2
      shift 2
      ;;
    --graph-name)
      GRAPH_NAME=$2
      shift 2
      ;;
    --audio-path)
      AUDIO_PATH=$2
      shift 2
      ;;
    --model-dir)
      MODEL_DIR=$2
      shift 2
      ;;
    --mfcc-config)
      MFCC_CONFIG=$2
      shift 2
      ;;
    --output-json)
      OUTPUT_JSON=$2
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
MODEL_DIR=$(resolve_model_dir "$RUNTIME_ROOT" "$MODEL_DIR")
if [[ -z "$OUTPUT_JSON" ]]; then
  OUTPUT_JSON="$RUNTIME_ROOT/manifests/t04_smoke_decode_${GRAPH_NAME}.json"
fi

ensure_file "$MANIFEST_PATH"

graph_meta_json=$(python3 - "$MANIFEST_PATH" "$GRAPH_NAME" <<'PY'
import json, sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
name = sys.argv[2]
for e in manifest["entries"]:
    if e["graph_name"] == name:
        print(json.dumps(e, ensure_ascii=True))
        raise SystemExit(0)
raise SystemExit(f"ERROR: graph not found in manifest: {name}")
PY
)

candidate_set=$(python3 - <<'PY' "$graph_meta_json"
import json, sys
e = json.loads(sys.argv[1])
print(json.dumps(e["candidate_words"], ensure_ascii=True))
PY
)

graph_dir=$(python3 - <<'PY' "$graph_meta_json"
import json, sys
e = json.loads(sys.argv[1])
print("" if e.get("graph_dir") is None else e["graph_dir"])
PY
)

lang_dir=$(python3 - <<'PY' "$graph_meta_json"
import json, sys
e = json.loads(sys.argv[1])
print(e["lang_dir"])
PY
)

best_candidate="null"
confidence="null"
lattice_path="null"
nbest_path="null"
notes=()

if [[ -z "$MFCC_CONFIG" && -f "$MODEL_DIR/mfcc.conf" ]]; then
  MFCC_CONFIG="$MODEL_DIR/mfcc.conf"
elif [[ -z "$MFCC_CONFIG" && -f "$MODEL_DIR/conf/mfcc.conf" ]]; then
  MFCC_CONFIG="$MODEL_DIR/conf/mfcc.conf"
fi
ONLINE_CONFIG=""
if [[ -f "$MODEL_DIR/online.conf" ]]; then
  ONLINE_CONFIG="$MODEL_DIR/online.conf"
elif [[ -f "$MODEL_DIR/conf/online.conf" ]]; then
  ONLINE_CONFIG="$MODEL_DIR/conf/online.conf"
fi
IVECTOR_DIR=""
if [[ -d "$MODEL_DIR/ivector_extractor" ]]; then
  IVECTOR_DIR="$MODEL_DIR/ivector_extractor"
fi

if [[ -z "$AUDIO_PATH" ]]; then
  notes+=("missing_audio_path")
fi
if [[ -z "$graph_dir" ]]; then
  notes+=("graph_dir_not_built_in_manifest")
fi
if [[ ! -f "$MODEL_DIR/final.mdl" ]]; then
  notes+=("missing_final.mdl")
fi
if [[ ! -d "$graph_dir" || ! -f "$graph_dir/HCLG.fst" ]]; then
  notes+=("missing_HCLG.fst")
fi
if [[ ! -f "$lang_dir/words.txt" ]]; then
  notes+=("missing_lang_words.txt")
fi
if [[ -n "$AUDIO_PATH" && ! -f "$AUDIO_PATH" ]]; then
  notes+=("audio_not_found")
fi
if [[ -z "$MFCC_CONFIG" || ! -f "$MFCC_CONFIG" ]]; then
  notes+=("missing_mfcc.conf")
fi
if [[ -z "$ONLINE_CONFIG" || ! -f "$ONLINE_CONFIG" ]]; then
  notes+=("missing_online.conf")
fi
if [[ -z "$IVECTOR_DIR" || ! -d "$IVECTOR_DIR" ]]; then
  notes+=("missing_ivector_extractor")
fi

if [[ ${#notes[@]} -eq 0 ]]; then
  tmp_dir=$(mktemp -d)
  lat_gz="$tmp_dir/lat.1.gz"
  spk2utt="$tmp_dir/spk2utt"
  wav_scp="$tmp_dir/wav.scp"
  echo "utt_smoke utt_smoke" > "$spk2utt"
  echo "utt_smoke $AUDIO_PATH" > "$wav_scp"

  if online2-wav-nnet3-latgen-faster \
      --online=false \
      --do-endpointing=false \
      --config="$ONLINE_CONFIG" \
      --mfcc-config="$MFCC_CONFIG" \
      --ivector-extraction-config="$MODEL_DIR/conf/ivector_extractor.conf" \
      --word-symbol-table="$lang_dir/words.txt" \
      --beam=15.0 \
      --lattice-beam=8.0 \
      --acoustic-scale=0.1 \
      "$MODEL_DIR/final.mdl" "$graph_dir/HCLG.fst" "ark:$spk2utt" "scp:$wav_scp" "ark:|gzip -c >$lat_gz"; then
    best_txt="$tmp_dir/best.txt"
    lattice-best-path --word-symbol-table="$lang_dir/words.txt" \
      "ark:gunzip -c $lat_gz|" ark,t:"$best_txt" >/dev/null 2>&1 || true
    if [[ -s "$best_txt" ]]; then
      hyp=$(awk 'NR==1{for(i=2;i<=NF;i++) printf("%s%s",$i,(i==NF?"":" ")); print ""}' "$best_txt")
      if [[ -n "$hyp" ]]; then
        best_candidate=$(python3 - <<'PY' "$hyp" "$lang_dir/words.txt"
import json
import sys

hyp = sys.argv[1].strip()
words = {}
for line in open(sys.argv[2], encoding="utf-8"):
    parts = line.strip().split()
    if len(parts) >= 2:
        words[parts[1]] = parts[0]

mapped = [words.get(tok, tok) for tok in hyp.split()]
print(json.dumps(" ".join(mapped), ensure_ascii=True))
PY
)
      fi
    fi
    lattice_path=$(python3 - <<'PY' "$lat_gz"
import json, sys
print(json.dumps(sys.argv[1], ensure_ascii=True))
PY
)
    notes+=("decode_success")
  else
    notes+=("decode_command_failed")
  fi
else
  notes+=("decode_skipped_due_to_missing_assets")
fi

notes_json=$(python3 - <<'PY' "${notes[@]}"
import json, sys
print(json.dumps(sys.argv[1:], ensure_ascii=True))
PY
)

mkdir -p "$(dirname "$OUTPUT_JSON")"
python3 - <<'PY' "$OUTPUT_JSON" "$GRAPH_NAME" "$candidate_set" "$best_candidate" "$confidence" "$lattice_path" "$nbest_path" "$notes_json"
import json, sys
out = {
    "graph_name": sys.argv[2],
    "candidate_set": json.loads(sys.argv[3]),
    "best_candidate": json.loads(sys.argv[4]) if sys.argv[4] != "null" else None,
    "confidence": None if sys.argv[5] == "null" else json.loads(sys.argv[5]),
    "lattice_path": None if sys.argv[6] == "null" else json.loads(sys.argv[6]),
    "nbest_path": None if sys.argv[7] == "null" else json.loads(sys.argv[7]),
    "notes": json.loads(sys.argv[8]),
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=True)
    f.write("\n")
print(f"Wrote smoke decode json: {sys.argv[1]}")
PY
