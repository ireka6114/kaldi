# Repository Guidelines

## Project Structure & Module Organization
- Core engine lives in `src/` (C++ binaries/libraries) and `tools/` (third-party deps).
- Example recipes live in `egs/` (each task has its own `s5`-style pipeline).
- Build system files are in `cmake/` and top-level `CMakeLists.txt`.
- Project docs are in `docs/`; platform-specific notes in `windows/` and `docker/`.
- Current custom work is under `egs/t04_en_constrained/s5/`:
  - `config/` task configs
  - `scripts/` build/decode/diagnostic scripts
  - `runtime/` generated graphs/manifests/results

## Build, Test, and Development Commands
- Classic build:
  - `cd tools && ./extras/check_dependencies.sh && make -j`
  - `cd ../src && ./configure && make -j`
- CMake build (alternative):
  - `cmake -S . -B build/Release && cmake --build build/Release -j`
- T04 pipeline (from repo root):
  - `./egs/t04_en_constrained/s5/scripts/build_t04_lang.sh`
  - `./egs/t04_en_constrained/s5/scripts/build_t04_grammars.sh`
  - `./egs/t04_en_constrained/s5/scripts/build_t04_graphs.sh`
  - `python3 egs/t04_en_constrained/s5/scripts/score_t04_micro_probes.py ...`

## Coding Style & Naming Conventions
- C++: follow Google C++ style with Kaldi exceptions (`kaldi-asr` conventions).
- Python: 4-space indentation, `snake_case`, explicit CLI args, JSON outputs `ensure_ascii=True`.
- Shell: `bash`, `set -euo pipefail`, lowercase script names, task-prefixed filenames (e.g., `t04_*`).
- Keep task-specific logic isolated; do not mix new task code into `t04_*` files.

## Testing Guidelines
- Validate build success before recipe testing.
- For recipe changes, run task-local checks:
  - `inspect_t04_graphs.sh` (graph/manifest consistency)
  - `check_t04_probe_health.py` (probe health diagnostics)
  - `score_t04_micro_probes.py` (end-to-end scoring outputs)
- Prefer reproducible artifacts in `runtime/diagnostic/` with explicit suffixes (e.g., `_human`).

## Commit & Pull Request Guidelines
- Use concise, imperative commit messages (seen in history: `Fix ...`, `Update ...`, optional `[build]` prefix).
- Keep commits scoped (build changes, recipe changes, docs changes separated when practical).
- PRs should include:
  - what changed and why
  - exact commands run
  - key output files/metrics paths
  - any environment/model assumptions

## Security & Configuration Tips
- Do not hardcode secrets or private tokens in scripts/configs.
- Avoid committing large generated artifacts (`runtime/`, model tarballs) unless explicitly required.
- Prefer environment files (e.g., `runtime/manifests/model_paths.env`) for local model path overrides.

## T04 Round-2 Pseudoword Redesign Guidance
- Current top priority is `T04` second-round stimulus de-risking, not scorer tuning and not AM retraining.
- Treat lexical-attraction risk as the dominant failure mode; redesign/audit work must focus on stimulus materials.
- Hard-ban real-word hits and specifically ban `bop` and `kope` in round-2 candidate generation.
- Preserve scorer logic, lexicon truth, and phones truth; do not alter those sources in this workstream.
- Preserve formal-level structure (`T04_CVC`, `T04_CVCE`, `T04_ING_A`, `T04_ING_B`) and reserved control pairs.
- All candidate decisions must be reproducible and traceable through local config+script outputs under `runtime/diagnostic/`.
- Keep `T01/T02` and `T12` work lightweight audits only in this phase (no redesign scope expansion).
- Host-project pseudoword integration should go through the unified adapter (`scripts/run_pseudoword_adapter.py`) and centralized config (`config/pseudoword_adapter_config.json`); do not couple the web project directly to task-local scorer scripts or WSL absolute paths.

## T04 Formal Candidate Guardrail
- `T04` round-2 post-activation candidate is `t04_formal_candidate_v1_1`; treat it as the active candidate package.
- For this phase, changes are item-level only unless broad failure patterns appear across multiple pairs and controls.
- Scorer logic, lexicon truth, phones truth, and AM retraining are not current T04 priorities.

## T04 Stable Pilot Note
- `T04` has reached `t04_stable_pilot_v1` status for normal trial use.
- `wut` is no longer an active watch item.
- `gepe` and `wytting` are the only active watch items (`light_watch` / `monitor_only`).
- Further T04 changes remain item-level only unless broad failures appear.

## Cross-Task Pseudoword Governance
- Pseudoword tasks are now under governance mode with monitoring-first maintenance.
- `T04` must not reopen broad redesign unless broad failures reappear across multiple pairs and controls.
- `T01/T02` should prefer instruction clarification and localized reserve handling only.
- `T12` should remain monitoring-only unless localized recurring drift appears.
