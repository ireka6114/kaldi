#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

MICRO_PROBE_JSON=""
RUNTIME_ROOT="$DEFAULT_RUNTIME_ROOT"
LANG_NAME="$DEFAULT_LANG_NAME"
MODEL_DIR=""
OUT_PREFIX="micro_probe"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --micro-probe-json)
      MICRO_PROBE_JSON=$2
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
    --model-dir)
      MODEL_DIR=$2
      shift 2
      ;;
    --out-prefix)
      OUT_PREFIX=$2
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$MICRO_PROBE_JSON" ]]; then
  echo "ERROR: --micro-probe-json is required" >&2
  exit 1
fi

RUNTIME_ROOT=$(realpath "$RUNTIME_ROOT")
MICRO_PROBE_JSON=$(realpath "$MICRO_PROBE_JSON")
MODEL_DIR=$(resolve_model_dir "$RUNTIME_ROOT" "$MODEL_DIR")

TMP_DIR=$(mktemp -d)
WORDS_JSON="$TMP_DIR/t04_micro_word_sets.json"
CONF_JSON="$TMP_DIR/t04_micro_confusion_sets.json"
MANIFEST_PATH="$RUNTIME_ROOT/manifests/${OUT_PREFIX}_graph_manifest.json"
PROBE_MANIFEST_PATH="$RUNTIME_ROOT/manifests/${OUT_PREFIX}_probe_manifest.json"

python3 - "$MICRO_PROBE_JSON" "$WORDS_JSON" "$CONF_JSON" <<'PY'
import json
import sys
from pathlib import Path

micro = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
target = micro.get("target_surface") or micro["target"].strip("_")
competitors = micro.get("competitors", [])
graph_name = f"T04_MICRO_{micro['item'].upper()}_{micro['probe_type'].upper()}"
family_name = f"{micro['item']}_family"
diagnostic_dimension = micro["probe_type"]
words = [target] + competitors
family_items = {word: words for word in words}

word_sets = {
    "task_id": "T04_EN",
    "formal_levels": {
        graph_name: {
            "level_tag": "MICRO",
            "source_set": "MICRO",
            "uses_levels": [],
            "words": words,
            "confusion_groups": [words],
        }
    },
    "demo_levels": {},
}

conf_sets = {
    "task_id": "T04_EN",
    "formal_default": {
        "candidate_policy": "item_plus_confusion_family_safe",
        "families": [
            {
                "family_name": family_name,
                "diagnostic_dimension": diagnostic_dimension,
                "items": family_items,
            }
        ],
    },
    "diagnostic_level_all": {
        "candidate_policy": "diagnostic_level_all",
        "enabled": True,
        "notes": "Temporary bridge config for shared-core micro-probe compilation.",
    },
    "optional_pseudoword_diagnostics": {
        "candidate_policy": "optional_pseudoword_diagnostics",
        "enabled_by_default": False,
        "items": {},
    },
}

Path(sys.argv[2]).write_text(json.dumps(word_sets, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
Path(sys.argv[3]).write_text(json.dumps(conf_sets, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
PY

bash "$KALDI_ROOT/egs/t04_en_constrained/s5/scripts/build_t04_grammars.sh" \
  --runtime-root "$RUNTIME_ROOT" \
  --lang-name "$LANG_NAME" \
  --config-json "$WORDS_JSON" \
  --confusion-config-json "$CONF_JSON" \
  --manifest-path "$MANIFEST_PATH" \
  --probe-manifest-path "$PROBE_MANIFEST_PATH"

bash "$KALDI_ROOT/egs/t04_en_constrained/s5/scripts/build_t04_graphs.sh" \
  --runtime-root "$RUNTIME_ROOT" \
  --lang-name "$LANG_NAME" \
  --manifest-path "$MANIFEST_PATH" \
  --probe-manifest-path "$PROBE_MANIFEST_PATH" \
  --model-dir "$MODEL_DIR"

rm -rf "$TMP_DIR"
echo "done: reused t04 micro-graph compiler for $MICRO_PROBE_JSON"
