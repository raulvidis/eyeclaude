# AGENTS.md

Work style: telegraph; noun-phrases ok; drop grammar; min tokens.

## Core
- Python 3.12+ project, pip/pip-tools (venv only, never swap)
- Pytest is the test framework — `pytest -q` for fast runs
- Release = git tag, not PyPI publish (no public release yet)
- Windows-only — never remove pywin32/Win32 API calls

## Routing
- Screenshots/assets → `docs/assets/`
- Secrets → env vars or `~/.eyeclaude/`, never echo
- Win32 APIs for window focus/hotkeys — use `win32gui`, `win32api`, `win32file`

## Project Defaults
- Package manager: pip (venv in `.venv/`, never swap)
- Bug fixes → add regression tests in `tests/`
- Refactors → delete old paths by default
- Session start + before coding: run $docs-list (`python3 .agents/skills/docs-list/scripts/docs-list.py`); read docs whose read_when matches
- Update docs for visible changes
- New deps → `pip install -e ".[dev]"` first, health check

## Reviews
- Pre-commit / pre-land: run $autoreview until no actionable findings remain
- $autoreview delegates to installed review skills (/code-review, superpowers) — don't hand-roll review

## PR / CI
- PR workflow: fix → test → changelog → review → merge
- "fix ci" = consent to pull, commit, push, rerun until green
- Always cite fix + file/line in review comments
- After landing: recap what landed (2-5 sentences)
- Contributor PRs: thank in changelog, preserve credit

## Git
- Safe by default (status/diff/log)
- Push only when asked
- Destructive ops forbidden without explicit consent
- Conventional Commits (feat|fix|refactor|docs|chore|test|build|ci|style|perf)
- No amend unless asked
- Unrecognized changes → assume other agent, keep going

## Runtime Safety
- Never run `set`, `export`, or broad env dumps on Windows
- Never inline shell snippets in GitHub bodies (use heredoc + file)
- Secrets: never run `setx`, `env` or broad secret dumps
- Pywin32 calls require Windows — mock on non-Windows

## Workflows
Procedures in `.agents/commands/`. To run one, read the file and follow it.
- handoff — package state for the next agent
- pickup — rehydrate context at session start
- commit — safe Conventional Commit
- fix — run quality gates, fix until green
- release — full release pipeline (see docs/RELEASING.md)
