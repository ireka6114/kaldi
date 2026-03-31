#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
S5_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
KALDI_ROOT=$(cd "$S5_ROOT/../../.." && pwd)
WSJ_S5="$KALDI_ROOT/egs/wsj/s5"
DEFAULT_DICT_DIR="/mnt/c/Users/11924/code/I-can-t-read-/engine/asr_evidence_engine/kaldi_runtime/lang/dict_T04_EN"
DEFAULT_RUNTIME_ROOT="$S5_ROOT/runtime"
DEFAULT_MODEL_ENV_FILE="manifests/model_paths.env"

setup_kaldi_path() {
  # shellcheck source=/dev/null
  . "$S5_ROOT/path.sh"
}

ensure_file() {
  local file=$1
  if [[ ! -f "$file" ]]; then
    echo "ERROR: missing file: $file" >&2
    exit 1
  fi
}

ensure_dir() {
  local dir=$1
  if [[ ! -d "$dir" ]]; then
    echo "ERROR: missing directory: $dir" >&2
    exit 1
  fi
}

json_bool() {
  if [[ "$1" == "true" ]]; then
    echo "true"
  else
    echo "false"
  fi
}

resolve_model_dir() {
  local runtime_root=$1
  local requested_model_dir=${2:-}
  local env_file="$runtime_root/$DEFAULT_MODEL_ENV_FILE"

  if [[ -n "$requested_model_dir" ]]; then
    echo "$requested_model_dir"
    return 0
  fi

  if [[ -f "$env_file" ]]; then
    # shellcheck source=/dev/null
    . "$env_file"
    if [[ -n "${T04_MODEL_DIR:-}" ]]; then
      echo "$T04_MODEL_DIR"
      return 0
    fi
  fi

  echo "$runtime_root/model"
}
