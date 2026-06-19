---
description: "Run quality gates and fix all failures."
---
Run the repo's quality gates and fix every failure until green:
- Lint: `ruff check .` (if ruff is installed)
- Type check: `mypy .` (if mypy is installed)
- Tests: `pytest -q`
- Build: `pip install -e .` (if cheap)

> Adapt these to the repo. Examples:
> - Python: `pytest` (+ ruff/mypy)
> - Gradle/Android: `./gradlew lint testDebugUnitTest assembleDebug`
> - pnpm/JS: `pnpm lint && pnpm build` (+ workspace tests)

Re-run until clean. Update docs/CHANGELOG for visible behavior changes.
Confirm `git status -sb` clean and on the expected branch.
