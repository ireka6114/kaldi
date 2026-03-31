#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <experiment_config.json> [output_root]" >&2
  exit 2
fi

CONF_JSON=$(python3 - <<'PY' "$1"
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)

OUT_ROOT=${2:-"egs/t04_en_constrained/s5/runtime/diagnostic/am_minpair_experiments"}
OUT_ROOT=$(python3 - <<'PY' "$OUT_ROOT"
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)

EXP_NAME=$(python3 - <<'PY' "$CONF_JSON"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(c.get('experiment_name','t04_minpair_quick'))
PY
)
TS=$(date +%Y%m%d_%H%M%S)
EXP_DIR="$OUT_ROOT/${EXP_NAME}_${TS}"
mkdir -p "$EXP_DIR"
cp "$CONF_JSON" "$EXP_DIR/experiment_config.json"

S5_ROOT=$(python3 - <<'PY' "$CONF_JSON"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
rt=Path(c['runtime_root']).resolve()
print(rt.parent)
PY
)

GEN_SCRIPT="/home/yoeseka/kaldi/egs/t04_en_constrained/s5/experiments/t04_am_minpair/scripts/generate_t04_minpair_manifests.py"
EVAL_SCRIPT="/home/yoeseka/kaldi/egs/t04_en_constrained/s5/experiments/t04_am_minpair/scripts/eval_t04_minpair_am.py"

python3 "$GEN_SCRIPT" --config "$EXP_DIR/experiment_config.json" --output-dir "$EXP_DIR/manifests"

BASELINE_MODEL_DIR=$(python3 - <<'PY' "$EXP_DIR/experiment_config.json"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(Path(c.get('baseline_model_dir','')).resolve() if c.get('baseline_model_dir') else '')
PY
)
if [[ -z "$BASELINE_MODEL_DIR" ]]; then
  echo "baseline_model_dir is required in config" >&2
  exit 3
fi

ADAPTED_MODEL_DIR=$(python3 - <<'PY' "$EXP_DIR/experiment_config.json"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
v=c.get('adapted_model_dir','').strip()
print(Path(v).resolve() if v else '')
PY
)
if [[ -z "$ADAPTED_MODEL_DIR" ]]; then
  ADAPTED_MODEL_DIR="$EXP_DIR/model_adapted"
fi

ADAPT_CMD=$(python3 - <<'PY' "$EXP_DIR/experiment_config.json"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(c.get('adaptation_command','').strip())
PY
)

TRAIN_MANIFEST="$EXP_DIR/manifests/minpair_train_manifest.jsonl"
DEV_MANIFEST="$EXP_DIR/manifests/minpair_dev_manifest.jsonl"
RUNTIME_ROOT=$(python3 - <<'PY' "$EXP_DIR/experiment_config.json"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(Path(c['runtime_root']).resolve())
PY
)
WAV_DIR=$(python3 - <<'PY' "$EXP_DIR/experiment_config.json"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(Path(c['eval_wav_dir']).resolve())
PY
)
FIXED_PAIRS=$(python3 - <<'PY' "$EXP_DIR/experiment_config.json"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(','.join(c.get('fixed_pairs',[])))
PY
)
CONTROL_PAIRS=$(python3 - <<'PY' "$EXP_DIR/experiment_config.json"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(','.join(c.get('control_pairs',[])))
PY
)
KNOWN_INDIST=$(python3 - <<'PY' "$EXP_DIR/experiment_config.json"
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(c.get('known_am_indistinguishable_pairs',''))
PY
)

if [[ -n "$ADAPT_CMD" ]]; then
  echo "Running adaptation command..."
  mkdir -p "$ADAPTED_MODEL_DIR"
  BASELINE_MODEL_DIR="$BASELINE_MODEL_DIR" \
  ADAPTED_MODEL_DIR="$ADAPTED_MODEL_DIR" \
  TRAIN_MANIFEST="$TRAIN_MANIFEST" \
  DEV_MANIFEST="$DEV_MANIFEST" \
  RUNTIME_ROOT="$RUNTIME_ROOT" \
  S5_ROOT="$S5_ROOT" \
  bash -lc "$ADAPT_CMD"
else
  echo "No adaptation_command provided. Creating scaffold symlink adapted_model_dir -> baseline_model_dir"
  if [[ -e "$ADAPTED_MODEL_DIR" && ! -L "$ADAPTED_MODEL_DIR" ]]; then
    echo "Refusing to overwrite existing non-symlink path: $ADAPTED_MODEL_DIR" >&2
    exit 4
  fi
  ln -sfn "$BASELINE_MODEL_DIR" "$ADAPTED_MODEL_DIR"
fi

python3 "$EVAL_SCRIPT" \
  --runtime-root "$RUNTIME_ROOT" \
  --wav-dir "$WAV_DIR" \
  --baseline-model-dir "$BASELINE_MODEL_DIR" \
  --adapted-model-dir "$ADAPTED_MODEL_DIR" \
  --experiment-dir "$EXP_DIR/eval" \
  --fixed-pairs "$FIXED_PAIRS" \
  --control-pairs "$CONTROL_PAIRS" \
  --known-am-indistinguishable-pairs "$KNOWN_INDIST"

cat <<EOF
Done.
Experiment dir: $EXP_DIR
Manifests:
  $EXP_DIR/manifests/minpair_train_manifest.jsonl
  $EXP_DIR/manifests/minpair_dev_manifest.jsonl
  $EXP_DIR/manifests/minpair_eval_manifest.jsonl
Eval reports:
  $EXP_DIR/eval/am_minpair_eval_report.json
  $EXP_DIR/eval/am_minpair_eval_report.md
EOF
