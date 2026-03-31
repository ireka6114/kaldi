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
