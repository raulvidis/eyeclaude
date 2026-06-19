Task 3: Eliminate shell injection in statusline installer

Problem: `cli.py:_install_statusline` builds a `bash -c '...'` command with an interpolated home path. Apostrophes, dollar signs, or backticks in the path produce arbitrary code that runs on every statusline refresh. Fix: extract composition to a Python entry point.

Files:
- Create: src/eyeclaude/statusline_command.py
- Modify: src/eyeclaude/cli.py (body of `_install_statusline`, ~lines 55-93)
- Modify: pyproject.toml (add a new entry-point line)
- Create: tests/test_statusline_command.py

Step 1 — Create `tests/test_statusline_command.py`:

```python
"""Tests for the eyeclaude-statusline composer."""

from pathlib import Path

import pytest

from eyeclaude import statusline_command as sc


def test_compose_indicator_and_ccstatusline(tmp_path, mocker):
    indicator_file = tmp_path / "indicator"
    indicator_file.write_text("\U0001f7e2◀", encoding="utf-8")
    mocker.patch.object(sc, "_run_ccstatusline", return_value="branch | model")
    mocker.patch.object(sc, "INDICATOR_PATH", indicator_file)
    assert sc.compose(stdin_data='{"foo":1}') == "\U0001f7e2◀ branch | model"


def test_compose_indicator_only_when_ccstatusline_fails(tmp_path, mocker):
    indicator_file = tmp_path / "indicator"
    indicator_file.write_text("X", encoding="utf-8")
    mocker.patch.object(sc, "_run_ccstatusline", return_value="")
    mocker.patch.object(sc, "INDICATOR_PATH", indicator_file)
    assert sc.compose(stdin_data="") == "X"


def test_compose_ccstatusline_only_when_no_indicator(tmp_path, mocker):
    mocker.patch.object(sc, "_run_ccstatusline", return_value="ccs-out")
    mocker.patch.object(sc, "INDICATOR_PATH", tmp_path / "missing")
    assert sc.compose(stdin_data="") == "ccs-out"


def test_compose_empty_when_neither(tmp_path, mocker):
    mocker.patch.object(sc, "_run_ccstatusline", return_value="")
    mocker.patch.object(sc, "INDICATOR_PATH", tmp_path / "missing")
    assert sc.compose(stdin_data="") == ""
```

Step 2 — Run `pytest tests/test_statusline_command.py -v`. Expected: FAIL.

Step 3 — Create `src/eyeclaude/statusline_command.py`:

```python
"""Statusline composer entry point.

Reads stdin (the JSON Claude Code feeds to statusline commands), invokes
ccstatusline through npx, prepends an EyeClaude indicator if present, and
writes the combined line to stdout. Pure Python -- no shell interpolation.
"""

import subprocess
import sys
from pathlib import Path

INDICATOR_PATH = Path.home() / ".eyeclaude" / "status" / "indicator"


def _run_ccstatusline(stdin_data: str) -> str:
    try:
        result = subprocess.run(
            ["npx", "-y", "ccstatusline@latest"],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _read_indicator() -> str:
    try:
        return INDICATOR_PATH.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""


def compose(stdin_data: str) -> str:
    indicator = _read_indicator()
    ccs = _run_ccstatusline(stdin_data)
    if indicator and ccs:
        return f"{indicator} {ccs}"
    return indicator or ccs


def main() -> None:
    stdin_data = ""
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read()
    sys.stdout.write(compose(stdin_data))


if __name__ == "__main__":
    main()
```

Step 4 — In `pyproject.toml`, find the `[project.scripts]` table. If an `eyeclaude-statusline = ...` line already exists, replace its value. Otherwise add:

```toml
eyeclaude-statusline = "eyeclaude.statusline_command:main"
```

Then run `pip install -e .` to register the entry point.

Step 5 — Run `pytest tests/test_statusline_command.py -v`. All 4 tests must pass.

Step 6 — In `src/eyeclaude/cli.py`, find the `_install_statusline()` function. Replace its entire body with:

```python
def _install_statusline():
    """Install EyeClaude indicator into Claude Code's statusline."""
    import shutil

    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    backup_path = Path.home() / ".eyeclaude" / "statusline_backup.json"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if "statusLine" in settings:
        backup_path.write_text(json.dumps(settings["statusLine"]), encoding="utf-8")

    composer = shutil.which("eyeclaude-statusline") or "eyeclaude-statusline"
    settings["statusLine"] = {
        "type": "command",
        "command": f'"{composer}"',
        "padding": 0,
    }
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    click.echo("Statusline indicator installed.")
```

Step 7 — Run `pytest -v` (full suite). All tests must pass.

Step 8 — Commit:
```
git add src/eyeclaude/statusline_command.py src/eyeclaude/cli.py pyproject.toml tests/test_statusline_command.py
git commit -m "fix: replace shell-interpolated statusline command with python entry point"
```

Then reply "Task 3 done." and stop.
