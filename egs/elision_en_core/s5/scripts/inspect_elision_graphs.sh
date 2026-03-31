#!/usr/bin/env bash

set -euo pipefail

MANIFEST_PATH="${1:-egs/elision_en_core/s5/runtime/manifests/elision_graph_manifest.json}"
PROBE_MANIFEST_PATH="${2:-egs/elision_en_core/s5/runtime/manifests/elision_probe_manifest.json}"

python3 - "$MANIFEST_PATH" "$PROBE_MANIFEST_PATH" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
probe_manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

for entry in manifest.get("entries", []):
    if entry.get("task_mode") != "shared_core":
        raise SystemExit(f"ERROR: task_mode mismatch for {entry['graph_name']}")
    if entry.get("applicable_tasks") != ["T01_EN", "T02_EN"]:
        raise SystemExit(f"ERROR: applicable_tasks mismatch for {entry['graph_name']}")
    if not entry.get("graph_dir") or not entry.get("lang_graph_path"):
        raise SystemExit(f"ERROR: missing graph paths for {entry['graph_name']}")
    if not entry.get("probe_type") or not entry.get("group"):
        raise SystemExit(f"ERROR: missing probe metadata for {entry['graph_name']}")

for entry in probe_manifest.get("entries", []):
    if entry.get("task_mode") != "shared_core":
        raise SystemExit(f"ERROR: probe task_mode mismatch for {entry['graph_name']}")

print(f"OK: shared-core graph manifest entries={len(manifest.get('entries', []))}")
print(f"OK: shared-core probe manifest entries={len(probe_manifest.get('entries', []))}")
PY
