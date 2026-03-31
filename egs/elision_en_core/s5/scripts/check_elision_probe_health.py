#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path


CASES = [
    {
        "utt_id": "health_a_fotting_human",
        "task_id": "T01_EN_STATIC",
        "item_id": "ELISION_A_FOTTING",
        "graph_name": "ELISION_ELISION_A_FOTTING_SYLLABLE_DELETION_PROBE",
        "wav_path": "egs/t04_en_constrained/s5/runtime/diagnostic/wavs_human_16k_base/fotting.wav"
    },
    {
        "utt_id": "health_a_gopping_human",
        "task_id": "T01_EN_STATIC",
        "item_id": "ELISION_A_GOPPING",
        "graph_name": "ELISION_ELISION_A_GOPPING_SYLLABLE_DELETION_PROBE",
        "wav_path": "egs/t04_en_constrained/s5/runtime/diagnostic/wavs_human_16k_base/gopping.wav"
    },
    {
        "utt_id": "health_b_wot_human",
        "task_id": "T01_EN_STATIC",
        "item_id": "ELISION_B_WOT",
        "graph_name": "ELISION_ELISION_B_WOT_PHONEME_DELETION_PROBE",
        "wav_path": "egs/t04_en_constrained/s5/runtime/diagnostic/wavs_human_16k_base/wot.wav"
    },
    {
        "utt_id": "health_b_zod_human",
        "task_id": "T01_EN_STATIC",
        "item_id": "ELISION_B_ZOD",
        "graph_name": "ELISION_ELISION_B_ZOD_PHONEME_DELETION_PROBE",
        "wav_path": "egs/t04_en_constrained/s5/runtime/diagnostic/wavs_human_16k_base/zod.wav"
    }
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Run shared-core probe health check against small human-audio samples.")
    ap.add_argument("--runtime-root", default="egs/elision_en_core/s5/runtime")
    ap.add_argument("--output-json", default="egs/elision_en_core/s5/runtime/diagnostic/elision_probe_health_report.json")
    ap.add_argument("--output-md", default="egs/elision_en_core/s5/runtime/diagnostic/elision_probe_health_report.md")
    args = ap.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    s5_root = runtime_root.parent
    tmp_trial = runtime_root / "diagnostic" / "elision_probe_health_trials.json"
    tmp_result = runtime_root / "diagnostic" / "elision_probe_health_results.json"
    tmp_csv = runtime_root / "diagnostic" / "elision_probe_health_results.csv"
    tmp_error = runtime_root / "diagnostic" / "elision_probe_health_error_item_ids.json"

    tmp_trial.write_text(
        json.dumps({"task_id": "T01_EN_STATIC", "core_task_id": "ELISION_EN_CORE", "entries": CASES}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    cmd = [
        "python3",
        str(s5_root / "scripts" / "score_elision_probes.py"),
        "--runtime-root",
        str(runtime_root),
        "--trial-manifest",
        str(tmp_trial),
        "--output-json",
        str(tmp_result),
        "--output-csv",
        str(tmp_csv),
        "--error-item-ids-out",
        str(tmp_error),
    ]
    subprocess.run(cmd, check=True)

    result = json.loads(tmp_result.read_text(encoding="utf-8"))
    rows = result["results"]
    passed = [r for r in rows if r["decision"] != "missing_score"]
    report = {
        "task_id": "ELISION_EN_CORE",
        "health_cases": rows,
        "pass_count": len(passed),
        "case_count": len(rows),
        "passed": len(passed) == len(rows),
    }
    out_json = Path(args.output_json).resolve()
    out_md = Path(args.output_md).resolve()
    out_json.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# ELISION_EN_CORE Probe Health Report",
        "",
        f"- passed: `{report['passed']}`",
        f"- pass_count: `{report['pass_count']}/{report['case_count']}`",
        "- validation_scope: `small human-audio sample, shared-core probe graphs only`",
        "",
    ]
    for row in rows:
        lines.append(f"- {row['item_id']} / {row['probe_type']} / decision={row['decision']} / best={row['best_candidate']}")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
