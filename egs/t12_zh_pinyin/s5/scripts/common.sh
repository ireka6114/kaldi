#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
S5_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
KALDI_ROOT=$(cd "$S5_ROOT/../../.." && pwd)
WSJ_S5="$KALDI_ROOT/egs/wsj/s5"
DEFAULT_DICT_DIR="$S5_ROOT/runtime/dict_T12_ZH_PINYIN_m11"
DEFAULT_RUNTIME_ROOT="$S5_ROOT/runtime"
DEFAULT_MODEL_ENV_FILE="manifests/model_paths.env"
DEFAULT_MODEL_MANIFEST_FILE="manifests/model_manifest.json"

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
    if [[ -n "${T12_MODEL_DIR:-}" ]]; then
      echo "$T12_MODEL_DIR"
      return 0
    fi
  fi

  echo "$runtime_root/model"
}

load_t12_model_env() {
  local runtime_root=$1
  local env_file="$runtime_root/$DEFAULT_MODEL_ENV_FILE"
  if [[ -f "$env_file" ]]; then
    # shellcheck source=/dev/null
    . "$env_file"
  fi
}

resolve_phone_symbol_table() {
  local runtime_root=$1
  local requested_phone_table=${2:-}

  if [[ -n "$requested_phone_table" ]]; then
    echo "$requested_phone_table"
    return 0
  fi

  load_t12_model_env "$runtime_root"
  if [[ -n "${T12_PHONES_TXT:-}" ]]; then
    echo "$T12_PHONES_TXT"
    return 0
  fi

  local model_dir
  model_dir=$(resolve_model_dir "$runtime_root" "")
  if [[ -f "$model_dir/phones.txt" ]]; then
    echo "$model_dir/phones.txt"
    return 0
  fi

  echo ""
}

resolve_model_asset() {
  local runtime_root=$1
  local asset_name=$2
  local fallback_path=${3:-}

  load_t12_model_env "$runtime_root"

  case "$asset_name" in
    final_mdl)
      if [[ -n "${T12_FINAL_MDL:-}" ]]; then
        echo "$T12_FINAL_MDL"
        return 0
      fi
      ;;
    tree)
      if [[ -n "${T12_TREE:-}" ]]; then
        echo "$T12_TREE"
        return 0
      fi
      ;;
    mfcc_conf)
      if [[ -n "${T12_MFCC_CONF:-}" ]]; then
        echo "$T12_MFCC_CONF"
        return 0
      fi
      ;;
    online_conf)
      if [[ -n "${T12_ONLINE_CONF:-}" ]]; then
        echo "$T12_ONLINE_CONF"
        return 0
      fi
      ;;
    ivector_extractor_dir)
      if [[ -n "${T12_IVECTOR_EXTRACTOR_DIR:-}" ]]; then
        echo "$T12_IVECTOR_EXTRACTOR_DIR"
        return 0
      fi
      ;;
    phones_txt)
      if [[ -n "${T12_PHONES_TXT:-}" ]]; then
        echo "$T12_PHONES_TXT"
        return 0
      fi
      ;;
    *)
      echo "ERROR: unknown asset_name=$asset_name" >&2
      exit 1
      ;;
  esac

  echo "$fallback_path"
}
