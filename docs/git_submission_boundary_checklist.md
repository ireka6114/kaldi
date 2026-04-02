# Git Submission Boundary Checklist

## Default Rule
- Commit code, config, and durable human documentation.
- Do not commit runtime outputs, local datasets, downloaded tool archives, model files, or ad hoc diagnostics unless there is an explicit reason to version them.

## Safe To Commit
- `scripts/`
- `config/`
- `docs/`
- `.github/workflows/`
- task-local `egs/.../config/`
- task-local `egs/.../scripts/`
- small hand-maintained JSON/YAML/MD files that define behavior or reproducible policy
- `candidates/` when the files are design inputs or reserve plans rather than generated outputs

## Do Not Commit By Default
- `/runtime/**`
- `egs/*/*/runtime/**`
- `egs/*/*/exp/`
- `egs/*/*/mfcc/`
- `egs/*/*/plp/`
- `egs/*/*/data/`
- model directories, decode lattices, FST binaries, wav/flac assets, CSV/JSON summaries produced by runs
- downloaded archives under `tools/`
- copied Windows metadata such as `*.Zone.Identifier`

## Current Repo Guidance
- `T04`, `T01/T02`, and `T12` governance docs belong in `docs/` and may be committed.
- machine-readable operational outputs under `runtime/diagnostic/` are local artifacts by default and should stay untracked unless explicitly promoted into a code-reviewed source-of-truth location
- host integration code belongs in `scripts/`, `config/`, `docs/`, and `.github/workflows/`

## Pre-Commit Check
Run these before committing:

```bash
git status --short
git diff --cached --name-only
```

Ask three questions:
- Is this file hand-maintained source, config, or durable documentation?
- Would another machine need this file to understand or reproduce logic, not just inspect one local run?
- Is this file small and reviewable in Git?

If any answer is `no`, do not commit it by default.

## Practical Commit Pattern
- Commit integration code and docs separately from workflow fixes.
- Keep runtime smoke outputs local.
- If a machine-readable artifact is important long-term, promote it deliberately into a reviewed source path instead of committing the whole runtime tree.
