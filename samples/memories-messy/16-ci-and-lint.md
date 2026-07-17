---
path: /conventions/ci-and-lint.md
category: convention
tags: ci, ruff, mypy, ruleset
---
# CI and lint rules every PR must meet

- `ruff check .` — line length 100, `E F I UP B` selected, `ANN` ignored in
  tests only.
- `mypy --strict` on `src/` only; all functions typed.
- Matrix: ubuntu + windows on Python 3.12.
- The aggregate CI job is literally named `test` and is a **required check in
  the branch ruleset** — renaming it in `ci.yml` silently blocks every merge.
  Do not rename it.
