# AGENTS.md

READ ./.agents/AGENTS.base.md BEFORE ANYTHING (skip if missing).

Repo-specific hard rules only. Shared rules (Reviews, PR/CI, Git, Runtime Safety,
generic Project Defaults, Workflows) live in `AGENTS.base.md` — do not duplicate them here.

## Core
- Python 3.12+ project, pip/pip-tools (venv only, never swap)
- Pytest is the test framework — `pytest -q` for fast runs
- Release = git tag, not PyPI publish (no public release yet)
- Windows-only — never remove pywin32/Win32 API calls

## Routing
- Screenshots/assets → `docs/assets/`
- Secrets → env vars or `~/.eyeclaude/`, never echo
- Win32 APIs for window focus/hotkeys — use `win32gui`, `win32api`, `win32file`

## Project Defaults (repo-specific)
- Package manager: pip (venv in `.venv/`, never swap)
- Bug fixes → add regression tests in `tests/`
- New deps → `pip install -e ".[dev]"` first, health check

## Runtime Safety (repo-specific)
- Pywin32 calls require Windows — mock on non-Windows

## Workflows (repo-specific additions)
Base lists the standard workflows. Add only commands unique to this repo here.
