# Repository Maintenance Notes

This fork carries task-specific work under `egs/t04_en_constrained/s5/`,
`egs/t12_zh_pinyin/s5/`, and related local documentation in `docs/`.

## 2026-04-01: file mode normalization sweep

This maintenance commit records a repository-wide executable-bit cleanup where a
large set of tracked files changed from `100755` to `100644` without content
edits.

Scope:
- The diff is metadata-only. No source text, configuration values, or model
  assets were changed as part of this sweep.
- The goal is to make repository status and future reviews easier to read by
  separating permission normalization from functional changes.

Notes for future maintenance:
- When reviewing a similar change, verify with `git diff --summary` and
  `git diff --numstat` that the diff is still metadata-only before batching it
  into a single commit.
- Keep recipe or runtime documentation updates in separate commits whenever the
  changes include real pipeline behavior differences.
- If Windows or WSL tooling keeps reintroducing file mode noise, review local
  Git settings such as `core.fileMode` before making further functional edits.