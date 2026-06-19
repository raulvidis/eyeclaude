---
description: "Run quality gates and fix all failures."
---
Run the repo's quality gates and fix every failure until green:
- Lint: `ruff check .` (if ruff is installed)
- Type check: `mypy .` (if mypy is installed)
- Tests: `pytest -q`
- Build/install: `pip install -e ".[dev]"` (venv only, never swap package manager)

Windows-only: keep pywin32/Win32 calls; mock them on non-Windows, don't remove.

Re-run until clean. Update docs/CHANGELOG for visible behavior changes.
Confirm `git status -sb` clean and on the expected branch.
