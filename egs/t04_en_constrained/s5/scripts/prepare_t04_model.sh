#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
MODEL_ROOT=""
MODEL_NAME="m13_librispeech_resolved"
OUT_JSON=""
OUT_ENV=""
FORCE_REBUILD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      RUNTIME_ROOT=$2
      shift 2
      ;;
    --model-root)
      MODEL_ROOT=$2
      shift 2
      ;;
    --model-name)
      MODEL_NAME=$2
      shift 2
      ;;
    --output-json)
      OUT_JSON=$2
      shift 2
      ;;
    --output-env)
      OUT_ENV=$2
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

if [[ -z "$MODEL_ROOT" ]]; then
  MODEL_ROOT="$RUNTIME_ROOT/model"
fi
if [[ -z "$OUT_JSON" ]]; then
  OUT_JSON="$RUNTIME_ROOT/manifests/model_manifest.json"
fi
if [[ -z "$OUT_ENV" ]]; then
  OUT_ENV="$RUNTIME_ROOT/manifests/model_paths.env"
fi

ensure_dir "$MODEL_ROOT"
mkdir -p "$(dirname "$OUT_JSON")" "$(dirname "$OUT_ENV")"

find_chain_model() {
  find "$MODEL_ROOT/exp" -type f -name final.mdl \
    | rg '/chain_cleaned/.+/final\.mdl$' \
    | head -n 1
}

find_extractor_dir() {
  find "$MODEL_ROOT/exp" -type f \
    | rg '/extractor/(final|[0-9]+)\.ie$' \
    | head -n 1 \
    | xargs -r dirname
}

CHAIN_FINAL=$(find_chain_model || true)
if [[ -z "$CHAIN_FINAL" ]]; then
  echo "ERROR: cannot locate chain final.mdl under $MODEL_ROOT/exp" >&2
  exit 1
fi
CHAIN_DIR=$(dirname "$CHAIN_FINAL")
CHAIN_TREE="$CHAIN_DIR/tree"
ensure_file "$CHAIN_TREE"

IEDIR=$(find_extractor_dir || true)
if [[ -z "$IEDIR" ]]; then
  echo "ERROR: cannot locate i-vector extractor under $MODEL_ROOT/exp" >&2
  exit 1
fi
for f in final.mat final.dubm splice_opts global_cmvn.stats online_cmvn.conf; do
  ensure_file "$IEDIR/$f"
done

IE_FILE="$IEDIR/final.ie"
if [[ ! -f "$IE_FILE" ]]; then
  IE_FILE=$(find "$IEDIR" -maxdepth 1 -type f | rg '/[0-9]+\.ie$' | sort | tail -n 1 || true)
fi
if [[ -z "$IE_FILE" || ! -f "$IE_FILE" ]]; then
  echo "ERROR: cannot locate usable i-vector extractor .ie file under $IEDIR" >&2
  exit 1
fi

KALDI_MFCC_CONF="$KALDI_ROOT/egs/librispeech/s5/conf/mfcc_hires.conf"
ensure_file "$KALDI_MFCC_CONF"

MODEL_DIR="$MODEL_ROOT/$MODEL_NAME"
CONF_DIR="$MODEL_DIR/conf"
IVECTOR_OUT="$MODEL_DIR/ivector_extractor"

if [[ "$FORCE_REBUILD" == "true" ]]; then
  rm -rf "$MODEL_DIR"
fi
mkdir -p "$CONF_DIR" "$IVECTOR_OUT"

cp -f "$CHAIN_FINAL" "$MODEL_DIR/final.mdl"
cp -f "$CHAIN_TREE" "$MODEL_DIR/tree"
cp -f "$KALDI_MFCC_CONF" "$CONF_DIR/mfcc.conf"
cp -f "$IE_FILE" "$IVECTOR_OUT/final.ie"
cp -f "$IEDIR/final.mat" "$IVECTOR_OUT/final.mat"
cp -f "$IEDIR/final.dubm" "$IVECTOR_OUT/final.dubm"
cp -f "$IEDIR/global_cmvn.stats" "$IVECTOR_OUT/global_cmvn.stats"
cp -f "$IEDIR/splice_opts" "$IVECTOR_OUT/splice_opts"
cp -f "$IEDIR/online_cmvn.conf" "$IVECTOR_OUT/online_cmvn.conf"
cp -f "$IEDIR/online_cmvn.conf" "$CONF_DIR/online_cmvn.conf"

awk '{for(i=1;i<=NF;i++) print $i}' "$IVECTOR_OUT/splice_opts" > "$CONF_DIR/splice.conf"

cat > "$CONF_DIR/ivector_extractor.conf" <<EOF
--splice-config=$CONF_DIR/splice.conf
--cmvn-config=$CONF_DIR/online_cmvn.conf
--lda-matrix=$IVECTOR_OUT/final.mat
--global-cmvn-stats=$IVECTOR_OUT/global_cmvn.stats
--diag-ubm=$IVECTOR_OUT/final.dubm
--ivector-extractor=$IVECTOR_OUT/final.ie
--num-gselect=5
--min-post=0.025
--posterior-scale=0.1
--max-remembered-frames=1000
--max-count=100
--ivector-period=10
EOF

cat > "$CONF_DIR/online.conf" <<EOF
--feature-type=mfcc
--mfcc-config=$CONF_DIR/mfcc.conf
--ivector-extraction-config=$CONF_DIR/ivector_extractor.conf
--endpoint.silence-phones=1:2:3:4:5:6:7:8:9:10
EOF

cat > "$OUT_ENV" <<EOF
T04_MODEL_NAME=$MODEL_NAME
T04_MODEL_ROOT=$MODEL_ROOT
T04_MODEL_DIR=$MODEL_DIR
T04_FINAL_MDL=$MODEL_DIR/final.mdl
T04_TREE=$MODEL_DIR/tree
T04_MFCC_CONF=$CONF_DIR/mfcc.conf
T04_ONLINE_CONF=$CONF_DIR/online.conf
T04_IVECTOR_EXTRACTOR_DIR=$IVECTOR_OUT
EOF

python3 - "$OUT_JSON" "$MODEL_NAME" "$MODEL_ROOT" "$MODEL_DIR" "$CHAIN_DIR" "$IEDIR" "$CONF_DIR/mfcc.conf" "$CONF_DIR/online.conf" "$IVECTOR_OUT" <<'PY'
import json
import sys
from pathlib import Path

out = {
    "model_name": sys.argv[2],
    "source": "kaldi_official_m13_librispeech",
    "model_root": sys.argv[3],
    "model_dir": sys.argv[4],
    "chain_source_dir": sys.argv[5],
    "extractor_source_dir": sys.argv[6],
    "final_mdl": f'{sys.argv[4]}/final.mdl',
    "tree": f'{sys.argv[4]}/tree',
    "mfcc_conf": sys.argv[7],
    "online_conf": sys.argv[8],
    "ivector_extractor_dir": sys.argv[9],
    "notes": [
        "online.conf is generated for nnet3/online2 decode",
        "this model phone set is ARPAbet-based and may be incompatible with custom T04 phone inventory",
    ],
}
path = Path(sys.argv[1])
path.write_text(json.dumps(out, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"Wrote model manifest: {path}")
PY

echo "Wrote model env: $OUT_ENV"
echo "Model dir ready: $MODEL_DIR"
