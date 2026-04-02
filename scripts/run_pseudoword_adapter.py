#!/usr/bin/env python3

import argparse
import base64
import importlib.util
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config" / "pseudoword_adapter_config.json"
DEFAULT_RUNS_ROOT = REPO_ROOT / "runtime" / "diagnostic" / "pseudoword_adapter_runs"


class AdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def resolve_repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def load_config(path: Path) -> Dict[str, Any]:
    cfg = load_json(path)
    tasks = cfg.get("tasks", {})
    for task_cfg in tasks.values():
        for key in [
            "active_business_source",
            "runtime_root",
            "config_json",
            "graph_manifest",
            "probe_manifest",
            "model_manifest",
            "items_json",
            "t01_rules_json",
            "t02_rules_json",
            "prepare_script",
            "score_script",
            "instruction_note_source",
            "monitoring_note_source",
        ]:
            if key in task_cfg:
                task_cfg[key] = str(resolve_repo_path(task_cfg[key]))
    return cfg


def require_task_cfg(config: Dict[str, Any], task_code: str) -> Dict[str, Any]:
    try:
        return config["tasks"][task_code]
    except KeyError as exc:
        raise AdapterError("unknown_task", f"Unsupported task_code: {task_code}") from exc


def check_task(task_code: str, task_cfg: Dict[str, Any]) -> Dict[str, Any]:
    required_paths = {}
    for key in [
        "active_business_source",
        "runtime_root",
        "config_json",
        "graph_manifest",
        "probe_manifest",
        "model_manifest",
        "items_json",
        "t01_rules_json",
        "t02_rules_json",
        "prepare_script",
        "score_script",
        "instruction_note_source",
        "monitoring_note_source",
    ]:
        if key in task_cfg:
            required_paths[key] = Path(task_cfg[key])

    checks = []
    for key, path in required_paths.items():
        checks.append({"name": key, "path": str(path), "exists": path.exists()})

    runtime_root = Path(task_cfg["runtime_root"])
    graph_root = runtime_root / "graphs"
    graphs_exist = graph_root.exists() and graph_root.is_dir()
    checks.append({"name": "graphs_dir", "path": str(graph_root), "exists": graphs_exist})

    status = "pass" if all(c["exists"] for c in checks) else "fail"
    return {
        "task_code": task_code,
        "status": status,
        "task_status": task_cfg.get("status"),
        "current_host_mode": task_cfg.get("current_host_mode"),
        "future_host_mode": task_cfg.get("future_host_mode"),
        "checks": checks,
    }


def parse_request(path: Path) -> Dict[str, Any]:
    req = load_json(path)
    if not isinstance(req, dict):
        raise AdapterError("invalid_request", "request-json must be a JSON object")
    return req


def ensure_audio_file(request: Dict[str, Any], work_dir: Path) -> Path:
    audio_path = request.get("audio_wav_path")
    audio_b64 = request.get("audio_b64")
    if audio_path:
        wav_path = Path(audio_path)
        if not wav_path.is_absolute():
            wav_path = (REPO_ROOT / wav_path).resolve()
        if not wav_path.exists():
            raise AdapterError("audio_not_found", f"audio_wav_path not found: {wav_path}")
        return wav_path
    if audio_b64:
        try:
            raw = base64.b64decode(audio_b64, validate=True)
        except Exception as exc:
            raise AdapterError("invalid_audio_b64", f"Failed to decode audio_b64: {exc}") from exc
        wav_path = work_dir / "request_audio.wav"
        wav_path.write_bytes(raw)
        return wav_path
    raise AdapterError("missing_audio", "audio_wav_path or audio_b64 is required for this task")


def ensure_t12_decode_evidence(request: Dict[str, Any], work_dir: Path) -> Path:
    if request.get("decode_evidence_json"):
        path = Path(request["decode_evidence_json"])
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        if not path.exists():
            raise AdapterError("decode_evidence_not_found", f"decode_evidence_json not found: {path}")
        return path
    if request.get("decode_evidence_items") is not None:
        path = work_dir / "decode_evidence.json"
        write_json(path, request["decode_evidence_items"])
        return path
    raise AdapterError(
        "missing_decode_evidence",
        "T12 currently requires decode_evidence_json or decode_evidence_items; direct wav formal mode is not enabled yet",
    )


def load_t04_module() -> Any:
    script_path = REPO_ROOT / "egs" / "t04_en_constrained" / "s5" / "scripts" / "score_t04_micro_probes.py"
    script_dir = str(script_path.parent)
    inserted = False
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
        inserted = True
    spec = importlib.util.spec_from_file_location("t04_micro_probe_module", script_path)
    if spec is None or spec.loader is None:
        raise AdapterError("import_error", f"Unable to load T04 script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted:
            try:
                sys.path.remove(script_dir)
            except ValueError:
                pass
    return module


def resolve_t04_target(request: Dict[str, Any], task_cfg: Dict[str, Any]) -> Dict[str, str]:
    business_manifest = load_json(Path(task_cfg["active_business_source"]))
    formal_levels = business_manifest.get("formal_levels", {})
    target_word = str(request.get("target_word") or request.get("item_id") or "").strip().lower()
    if not target_word:
        raise AdapterError("missing_target_word", "T04 request requires target_word or item_id")

    for level_name, words in formal_levels.items():
        if target_word in words:
            return {
                "target_word": target_word,
                "parent_level_graph": level_name,
                "level_name": level_name.replace("T04_", ""),
            }
    raise AdapterError("unknown_t04_item", f"T04 target not found in active business manifest: {target_word}")


def modal_candidate(probes: List[Dict[str, Any]]) -> str | None:
    values = [p.get("best_candidate") for p in probes if p.get("best_candidate")]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def run_t04_single_item(request: Dict[str, Any], task_cfg: Dict[str, Any], work_dir: Path) -> Dict[str, Any]:
    module = load_t04_module()
    thresholds = task_cfg.get("thresholds", {})
    runtime_root = Path(task_cfg["runtime_root"])
    probe_manifest = load_json(Path(task_cfg["probe_manifest"]))
    target_info = resolve_t04_target(request, task_cfg)
    wav_path = ensure_audio_file(request, work_dir)

    probes_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for probe in probe_manifest.get("entries", []):
        probes_by_key[(str(probe.get("parent_level_graph")), str(probe.get("target_word")))].append(probe)

    key = (target_info["parent_level_graph"], target_info["target_word"])
    probes = probes_by_key.get(key, [])
    if not probes:
        raise AdapterError("missing_probe_entries", f"No T04 probes found for {key[0]}:{key[1]}")

    model_manifest = load_json(Path(task_cfg["model_manifest"]))
    model_dir = Path(model_manifest["model_dir"]).resolve()
    s5_root = runtime_root.parent
    known_pairs = module.parse_pair_set(module.DEFAULT_AM_INDISTINGUISHABLE_PAIRS)

    probe_results = []
    for probe in probes:
        graph_path = Path(probe.get("graph_path") or "").resolve()
        lang_graph_path = Path(probe.get("lang_graph_path") or "").resolve()
        words_txt = lang_graph_path / "words.txt"
        evidence = module.run_decode_constrained(
            wav_path=wav_path,
            graph_dir=graph_path,
            words_txt=words_txt,
            model_dir=model_dir,
            s5_root=s5_root,
            nbest_n=int(thresholds.get("nbest_n", 10)),
            acoustic_scale=float(thresholds.get("acoustic_scale", 0.1)),
        )
        local_vowel_evidence = None
        if (probe.get("probe_type") or "") == "vowel_probe":
            cand_words = probe.get("candidate_words", [])
            local_comp = next((w for w in cand_words if w != target_info["target_word"]), None)
            local_vowel_evidence = module.build_vowel_local_evidence(
                runtime_root=runtime_root,
                s5_root=s5_root,
                model_dir=model_dir,
                wav_path=wav_path,
                target_word=target_info["target_word"],
                competitor_word=local_comp,
                probe_evidence=evidence,
                acoustic_scale=float(thresholds.get("acoustic_scale", 0.1)),
            )
        scored = module.score_one_probe(
            target_word=target_info["target_word"],
            probe=probe,
            evidence=evidence,
            margin_threshold=float(thresholds.get("margin_threshold", 0.0)),
            small_margin_threshold=float(thresholds.get("small_margin_threshold", 0.05)),
            duration_threshold=float(thresholds.get("duration_threshold", 1.2)),
            local_vowel_evidence=local_vowel_evidence,
            vowel_local_margin_threshold=float(thresholds.get("vowel_local_margin_threshold", 0.05)),
            known_am_indistinguishable_pairs=known_pairs,
        )
        probe_results.append(scored)

    best_candidate = modal_candidate(probe_results)
    target_posteriors = [float(p.get("target_posterior") or 0.0) for p in probe_results]
    confidence = min(target_posteriors) if target_posteriors else 0.0
    has_reject = any(p.get("decision") == "reject" for p in probe_results)
    all_best_match = all((p.get("best_candidate") or "") == target_info["target_word"] for p in probe_results)
    is_correct = bool(all_best_match and not has_reject)
    item_score = 1.0 if is_correct else 0.0

    internal = {
        "target_word": target_info["target_word"],
        "parent_level_graph": target_info["parent_level_graph"],
        "level_name": target_info["level_name"],
        "wav_path": str(wav_path),
        "formal_probe_results": probe_results,
    }
    write_json(work_dir / "t04_single_item_internal.json", internal)

    return {
        "ok": True,
        "request_id": str(request.get("request_id") or ""),
        "task_code": "T04_EN_DYNAMIC",
        "item_id": str(request.get("item_id") or target_info["target_word"]),
        "engine": "kaldi_wfst",
        "mode": "formal",
        "score_source": "kaldi_wfst",
        "asr_transcript": best_candidate,
        "is_correct": is_correct,
        "item_score": item_score,
        "confidence": confidence,
        "source": "pseudoword_adapter_v1",
        "extra": {
            "kaldi_wfst": {
                "task_status": task_cfg.get("status"),
                "business_version": load_json(Path(task_cfg["active_business_source"]))["version"],
                "target_word": target_info["target_word"],
                "parent_level_graph": target_info["parent_level_graph"],
                "probe_results": probe_results,
                "artifacts": {
                    "internal_json": str(work_dir / "t04_single_item_internal.json")
                }
            }
        }
    }


def build_elision_trial(task_code: str, request: Dict[str, Any], task_cfg: Dict[str, Any], wav_path: Path) -> Dict[str, Any]:
    item_id = str(request.get("item_id") or "").strip()
    if not item_id:
        raise AdapterError("missing_item_id", f"{task_code} request requires item_id")
    items = {item["item_id"]: item for item in load_json(Path(task_cfg["items_json"]))["items"]}
    probe_manifest = load_json(Path(task_cfg["probe_manifest"]))["entries"]
    probe_by_item = {entry["item_id"]: entry for entry in probe_manifest}
    if item_id not in items or item_id not in probe_by_item:
        raise AdapterError("unknown_item", f"Unknown shared-core item_id: {item_id}")
    item = items[item_id]
    entry = probe_by_item[item_id]
    internal_task_id = "T01_EN_STATIC" if task_code == "T01_EN_PHONDEL" else "T02_EN_DYNAMIC"
    return {
        "task_id": internal_task_id,
        "core_task_id": "ELISION_EN_CORE",
        "entries": [
            {
                "utt_id": f"adapter_{task_code.lower()}_{item_id.lower()}",
                "task_id": internal_task_id,
                "item_id": item_id,
                "group": item["group"],
                "graph_name": entry["graph_name"],
                "wav_path": str(wav_path),
            }
        ],
    }


def run_subprocess(cmd: List[str]) -> None:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AdapterError(
            "subprocess_failed",
            f"Command failed: {' '.join(cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
        )


def run_elision_single_item(task_code: str, request: Dict[str, Any], task_cfg: Dict[str, Any], work_dir: Path) -> Dict[str, Any]:
    wav_path = ensure_audio_file(request, work_dir)
    trial_manifest = build_elision_trial(task_code, request, task_cfg, wav_path)
    trial_manifest_path = work_dir / "trial_manifest.json"
    result_json = work_dir / "score_result.json"
    result_csv = work_dir / "score_result.csv"
    error_ids_out = work_dir / "error_item_ids.json"
    write_json(trial_manifest_path, trial_manifest)

    model_manifest = load_json(Path(task_cfg["model_manifest"]))
    cmd = [
        sys.executable,
        str(Path(task_cfg["score_script"])),
        "--runtime-root",
        task_cfg["runtime_root"],
        "--probe-manifest",
        task_cfg["probe_manifest"],
        "--trial-manifest",
        str(trial_manifest_path),
        "--model-dir",
        model_manifest["model_dir"],
        "--output-json",
        str(result_json),
        "--output-csv",
        str(result_csv),
        "--error-item-ids-out",
        str(error_ids_out),
        "--margin-threshold",
        str(task_cfg.get("thresholds", {}).get("margin_threshold", 0.0)),
        "--acoustic-scale",
        str(task_cfg.get("thresholds", {}).get("acoustic_scale", 0.1)),
    ]
    run_subprocess(cmd)

    result = load_json(result_json)
    one = result["results"][0]
    candidate_posteriors = one.get("candidate_posteriors") or {}
    target_conf = 0.0
    best_candidate = one.get("best_candidate")
    if best_candidate and best_candidate in candidate_posteriors:
        target_conf = float(candidate_posteriors.get(best_candidate) or 0.0)

    instruction_note = load_json(Path(task_cfg["instruction_note_source"]))
    return {
        "ok": True,
        "request_id": str(request.get("request_id") or ""),
        "task_code": task_code,
        "item_id": one["item_id"],
        "engine": "kaldi_wfst",
        "mode": "formal",
        "score_source": "kaldi_wfst",
        "asr_transcript": best_candidate,
        "is_correct": one.get("decision") == "accept",
        "item_score": 1.0 if one.get("decision") == "accept" else 0.0,
        "confidence": target_conf,
        "source": "pseudoword_adapter_v1",
        "extra": {
            "kaldi_wfst": {
                "task_status": task_cfg.get("status"),
                "comparison_scope": one.get("comparison_scope"),
                "probe_type": one.get("probe_type"),
                "decision": one.get("decision"),
                "error_type": one.get("error_type"),
                "instruction_notes_applied": True,
                "instruction_note": instruction_note,
                "artifacts": {
                    "trial_manifest": str(trial_manifest_path),
                    "result_json": str(result_json),
                    "result_csv": str(result_csv),
                    "error_item_ids_json": str(error_ids_out)
                }
            }
        }
    }


def run_t12(request: Dict[str, Any], task_cfg: Dict[str, Any], work_dir: Path) -> Dict[str, Any]:
    desired_mode = str(request.get("options", {}).get("desired_mode") or task_cfg.get("current_host_mode") or "shadow").strip()
    if desired_mode == "formal" and task_cfg.get("current_host_mode") != "formal_single_item":
        raise AdapterError(
            "unsupported_current_mode",
            "T12 formal single-item mode is not enabled yet; current adapter supports decode-evidence shadow mode with a future config switch path",
        )
    evidence_json = ensure_t12_decode_evidence(request, work_dir)
    result_json = work_dir / "t12_result.json"
    summary_json = work_dir / "t12_summary.json"
    result_csv = work_dir / "t12_result.csv"

    cmd = [
        sys.executable,
        str(Path(task_cfg["score_script"])),
        "--runtime-root",
        task_cfg["runtime_root"],
        "--probe-manifest",
        task_cfg["probe_manifest"],
        "--decode-evidence-json",
        str(evidence_json),
        "--margin-threshold",
        str(task_cfg.get("thresholds", {}).get("margin_threshold", 0.0)),
        "--output-json",
        str(result_json),
        "--summary-json",
        str(summary_json),
        "--output-csv",
        str(result_csv),
    ]
    run_subprocess(cmd)

    result = load_json(result_json)
    summary = result.get("summary") or load_json(summary_json)
    grouped = result.get("results") or []
    target_word = str(request.get("target_word") or request.get("item_id") or "")
    one = None
    for entry in grouped:
        if str(entry.get("target_word") or "") == target_word:
            one = entry
            break
    if one is None and grouped:
        one = grouped[0]

    best_candidates = []
    if one:
        for probe in one.get("probes", []):
            if probe.get("best_candidate"):
                best_candidates.append(probe["best_candidate"])
    asr_transcript = Counter(best_candidates).most_common(1)[0][0] if best_candidates else None

    return {
        "ok": True,
        "request_id": str(request.get("request_id") or ""),
        "task_code": "T12_ZH_PINYIN",
        "item_id": str(request.get("item_id") or target_word),
        "engine": "kaldi_wfst",
        "mode": "shadow",
        "score_source": "shadow_only",
        "asr_transcript": asr_transcript,
        "is_correct": None,
        "item_score": None,
        "confidence": None,
        "source": "pseudoword_adapter_v1",
        "extra": {
            "kaldi_wfst": {
                "task_status": task_cfg.get("status"),
                "current_host_mode": task_cfg.get("current_host_mode"),
                "future_host_mode": task_cfg.get("future_host_mode"),
                "formalization_note": task_cfg.get("formalization_note"),
                "summary": summary,
                "artifacts": {
                    "decode_evidence_json": str(evidence_json),
                    "result_json": str(result_json),
                    "summary_json": str(summary_json),
                    "result_csv": str(result_csv)
                }
            }
        }
    }


def execute_request(request: Dict[str, Any], config: Dict[str, Any], keep_artifacts: bool = True) -> Dict[str, Any]:
    task_code = str(request.get("task_code") or "").strip()
    if not task_code:
        raise AdapterError("missing_task_code", "request.task_code is required")
    task_cfg = require_task_cfg(config, task_code)
    request_id = str(request.get("request_id") or f"{task_code.lower()}_{int(time.time())}")
    run_root = DEFAULT_RUNS_ROOT / request_id
    run_root.mkdir(parents=True, exist_ok=True)

    try:
        if task_code == "T04_EN_DYNAMIC":
            response = run_t04_single_item(request, task_cfg, run_root)
        elif task_code in {"T01_EN_PHONDEL", "T02_EN_DYNAMIC_PHONDEL"}:
            response = run_elision_single_item(task_code, request, task_cfg, run_root)
        elif task_code == "T12_ZH_PINYIN":
            response = run_t12(request, task_cfg, run_root)
        else:
            raise AdapterError("unknown_task", f"Unsupported task_code: {task_code}")
    except AdapterError as exc:
        response = {
            "ok": False,
            "request_id": request_id,
            "task_code": task_code,
            "item_id": str(request.get("item_id") or request.get("target_word") or ""),
            "engine": "kaldi_wfst",
            "mode": task_cfg.get("current_host_mode"),
            "score_source": "fallback",
            "asr_transcript": None,
            "is_correct": None,
            "item_score": None,
            "confidence": None,
            "source": "pseudoword_adapter_v1",
            "fallback_reason": exc.code,
            "error_message": exc.message,
            "extra": {
                "kaldi_wfst": {
                    "task_status": task_cfg.get("status"),
                    "current_host_mode": task_cfg.get("current_host_mode"),
                    "future_host_mode": task_cfg.get("future_host_mode")
                }
            }
        }

    write_json(run_root / "adapter_response.json", response)
    return response


def prepare_trials(task_code: str, task_cfg: Dict[str, Any], wav_root: str, output_json: str, error_item_ids: str | None) -> Dict[str, Any]:
    wav_root_path = Path(wav_root).resolve()
    output_json_path = Path(output_json).resolve()
    if task_code == "T01_EN_PHONDEL":
        cmd = [
            sys.executable,
            str(Path(task_cfg["prepare_script"])),
            "--items-json",
            task_cfg["items_json"],
            "--t01-rules-json",
            task_cfg["t01_rules_json"],
            "--probe-manifest",
            task_cfg["probe_manifest"],
            "--wav-root",
            str(wav_root_path),
            "--output-json",
            str(output_json_path),
        ]
    elif task_code == "T02_EN_DYNAMIC_PHONDEL":
        if not error_item_ids:
            raise AdapterError("missing_error_item_ids", "prepare for T02 requires --error-item-ids")
        error_ids_path = Path(error_item_ids).resolve()
        cmd = [
            sys.executable,
            str(Path(task_cfg["prepare_script"])),
            "--items-json",
            task_cfg["items_json"],
            "--t01-rules-json",
            task_cfg["t01_rules_json"],
            "--t02-rules-json",
            task_cfg["t02_rules_json"],
            "--probe-manifest",
            task_cfg["probe_manifest"],
            "--error-item-ids",
            str(error_ids_path),
            "--wav-root",
            str(wav_root_path),
            "--output-json",
            str(output_json_path),
        ]
    else:
        raise AdapterError("unsupported_prepare_task", f"prepare is only supported for T01/T02, got {task_code}")

    run_subprocess(cmd)
    manifest = load_json(output_json_path)
    return {
        "ok": True,
        "task_code": task_code,
        "output_json": str(output_json_path),
        "entry_count": len(manifest.get("entries", [])),
        "task_id": manifest.get("task_id"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Unified host-facing adapter for pseudoword task scoring.")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    sub = ap.add_subparsers(dest="command", required=True)

    check_ap = sub.add_parser("check", help="Validate adapter-ready task assets.")
    check_ap.add_argument("--task", default="")
    check_ap.add_argument("--all", action="store_true")
    check_ap.add_argument("--output-json", default="")

    run_ap = sub.add_parser("run", help="Run one host-facing scoring request.")
    run_ap.add_argument("--request-json", required=True)
    run_ap.add_argument("--output-json", default="")

    prep_ap = sub.add_parser("prepare", help="Prepare T01/T02 trial manifests using existing task-local scripts.")
    prep_ap.add_argument("--task", required=True)
    prep_ap.add_argument("--wav-root", required=True)
    prep_ap.add_argument("--output-json", required=True)
    prep_ap.add_argument("--error-item-ids", default="")

    args = ap.parse_args()
    config = load_config(Path(args.config))

    if args.command == "check":
        if args.all:
            task_codes = sorted(config["tasks"].keys())
        elif args.task:
            task_codes = [args.task]
        else:
            raise SystemExit("check requires --task or --all")
        out = {
            "adapter_version": config.get("version"),
            "generated_at_epoch": int(time.time()),
            "results": [check_task(code, require_task_cfg(config, code)) for code in task_codes],
        }
        out["overall_status"] = "pass" if all(r["status"] == "pass" for r in out["results"]) else "fail"
        if args.output_json:
            write_json(Path(args.output_json).resolve(), out)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return 0 if out["overall_status"] == "pass" else 1

    if args.command == "run":
        response = execute_request(parse_request(Path(args.request_json).resolve()), config)
        if args.output_json:
            write_json(Path(args.output_json).resolve(), response)
        print(json.dumps(response, ensure_ascii=True, indent=2))
        return 0 if response.get("ok") else 1

    if args.command == "prepare":
        response = prepare_trials(
            task_code=args.task,
            task_cfg=require_task_cfg(config, args.task),
            wav_root=args.wav_root,
            output_json=args.output_json,
            error_item_ids=args.error_item_ids or None,
        )
        print(json.dumps(response, ensure_ascii=True, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
