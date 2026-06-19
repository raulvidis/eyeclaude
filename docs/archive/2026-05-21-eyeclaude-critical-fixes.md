# EyeClaude Critical Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the highest-impact issues from the code analysis: a shell-injection in the statusline installer, an unverified model download, silently-dropped IPC failures, stale-terminal accumulation, and broken multi-monitor quadrant assignment.

**Architecture:** Six focused tasks, each with a failing test, minimal implementation, and a commit. No new modules — all changes are surgical edits to existing files plus one new helper module (`statusline_command.py`) extracted from `cli.py` to make the shell-free statusline command testable.

**Tech Stack:** Python 3.12+, pytest, pytest-mock, pywin32, MediaPipe, Click. Windows-only.

**Issues addressed (in execution order):**
1. Multi-monitor quadrant logic uses primary-screen metrics instead of the window's own monitor.
2. MediaPipe model is downloaded without integrity verification.
3. Statusline installer interpolates an unescaped path into `bash -c`.
4. `hooks.py` silently swallows pipe-write errors with no diagnostics.
5. Closed terminals are never unregistered; the list accumulates dead entries.
6. `hooks.py` has zero test coverage.

**Out of scope:** Drift detection, HiDPI, IRIS_GAZE_WEIGHT_Y empirical retuning, recalibration resource-recovery, settings.json atomic writes, overlay title-restore-on-crash. These are real issues, but lower priority — defer to a follow-up plan.

---

## File Structure

**New files:**
- `src/eyeclaude/statusline_command.py` — pure-Python statusline composition (extracted from `cli.py`).
- `tests/test_hooks.py` — unit tests for `hooks.main()`.
- `tests/test_statusline_command.py` — unit tests for the new module.

**Modified files:**
- `src/eyeclaude/pipe_server.py` — `_assign_quadrant_by_position` uses per-monitor work area.
- `src/eyeclaude/eye_tracker.py` — `ensure_model()` verifies SHA-256.
- `src/eyeclaude/cli.py` — `_install_statusline` calls the new composer via a Python script invocation (no `bash -c`); main loop prunes stale terminals.
- `src/eyeclaude/hooks.py` — failures append to `~/.eyeclaude/hooks.log` instead of being silently swallowed.
- `src/eyeclaude/shared_state.py` — add `unregister_terminal_by_hwnd()` if not already present (verify first).

---

## Task 1: Multi-monitor quadrant logic

**Problem.** `pipe_server.py:_assign_quadrant_by_position` uses `GetSystemMetrics(0/1)`, which returns the **primary** monitor's size. A window on a second monitor whose center is at `x=3000, y=500` is compared against e.g. a 1920×1080 primary screen — it always gets classified as `TOP_RIGHT` regardless of where on the secondary monitor it actually lives. Fix: use `MonitorFromWindow` + `GetMonitorInfo` to compute the quadrant relative to the monitor that owns the window.

**Files:**
- Modify: `src/eyeclaude/pipe_server.py:48-72`
- Test: `tests/test_pipe_server.py` (add new test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipe_server.py`:

```python
def test_assign_quadrant_uses_window_monitor_not_primary_screen(mocker):
    """A window on a secondary monitor should be quadranted within that monitor's
    work area, not against the primary screen's resolution."""
    from eyeclaude.pipe_server import _assign_quadrant_by_position
    from eyeclaude.shared_state import Quadrant

    # Window sitting on a virtual second monitor at x>=1920.
    # Window rect: (2400, 100, 3200, 600) → center (2800, 350)
    mocker.patch("win32gui.GetWindowRect", return_value=(2400, 100, 3200, 600))

    # MonitorFromWindow returns a handle; GetMonitorInfo returns the monitor's work area
    # as a dict with "Work" key (left, top, right, bottom).
    fake_monitor_handle = 12345
    mocker.patch("win32api.MonitorFromWindow", return_value=fake_monitor_handle)
    mocker.patch(
        "win32api.GetMonitorInfo",
        return_value={"Work": (1920, 0, 3840, 1080), "Monitor": (1920, 0, 3840, 1080)},
    )

    # Center (2800, 350) inside monitor work area (1920..3840 × 0..1080):
    # mid_x = (1920+3840)/2 = 2880 → 2800 < 2880 → LEFT
    # mid_y = (0+1080)/2 = 540 → 350 < 540 → TOP
    assert _assign_quadrant_by_position(99) == Quadrant.TOP_LEFT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipe_server.py::test_assign_quadrant_uses_window_monitor_not_primary_screen -v`
Expected: FAIL — current code uses `GetSystemMetrics`, will likely return `BOTTOM_RIGHT` or similar.

- [ ] **Step 3: Replace `_assign_quadrant_by_position` implementation**

In `src/eyeclaude/pipe_server.py`, replace the function (lines 48–72) with:

```python
def _assign_quadrant_by_position(window_handle: int) -> Quadrant:
    """Determine which quadrant a window occupies within ITS OWN monitor.

    Uses MonitorFromWindow to find the monitor hosting the window, then
    quadrants the window's center against that monitor's work area. This
    is correct for multi-monitor setups; primary-screen GetSystemMetrics
    is not.
    """
    try:
        import win32gui
        left, top, right, bottom = win32gui.GetWindowRect(window_handle)
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2

        # MONITOR_DEFAULTTONEAREST = 2
        monitor_handle = win32api.MonitorFromWindow(window_handle, 2)
        info = win32api.GetMonitorInfo(monitor_handle)
        m_left, m_top, m_right, m_bottom = info["Work"]

        mid_x = (m_left + m_right) / 2
        mid_y = (m_top + m_bottom) / 2

        if center_x < mid_x:
            if center_y < mid_y:
                return Quadrant.TOP_LEFT
            return Quadrant.BOTTOM_LEFT
        else:
            if center_y < mid_y:
                return Quadrant.TOP_RIGHT
            return Quadrant.BOTTOM_RIGHT
    except Exception:
        logger.warning("Could not determine window position, defaulting to TOP_LEFT")
        return Quadrant.TOP_LEFT
```

- [ ] **Step 4: Run the new test plus the existing pipe_server tests**

Run: `pytest tests/test_pipe_server.py -v`
Expected: all PASS. If any pre-existing test mocked `win32api.GetSystemMetrics` to drive quadrant assignment, update it to mock `win32api.MonitorFromWindow` + `win32api.GetMonitorInfo` instead — fix one at a time, re-run.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/pipe_server.py tests/test_pipe_server.py
git commit -m "fix: quadrant assignment uses window's own monitor work area"
```

---

## Task 2: Verify MediaPipe model integrity

**Problem.** `eye_tracker.py:ensure_model()` downloads the FaceLandmarker model from `storage.googleapis.com` over HTTPS but does not verify the bytes. If the URL is ever redirected, the bucket is compromised, or the download is corrupted mid-stream, EyeClaude silently runs with a wrong model — could crash MediaPipe at init, or worse, silently degrade. Fix: pin a SHA-256, verify after download, delete + raise on mismatch.

**Files:**
- Modify: `src/eyeclaude/eye_tracker.py:42-54`
- Test: `tests/test_eye_tracker.py` (add new test)

- [ ] **Step 1: Compute the current model's SHA-256 (one-time, outside the plan)**

Run (in PowerShell): `Get-FileHash $env:USERPROFILE\.eyeclaude\face_landmarker.task -Algorithm SHA256`

If the model isn't downloaded yet, run `eyeclaude calibrate` once to fetch it, then hash. Record the value — you will paste it into the next step as `MODEL_SHA256`.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_eye_tracker.py`:

```python
def test_ensure_model_rejects_wrong_sha(tmp_path, mocker):
    """A model file whose SHA-256 doesn't match the pinned value must be
    deleted and ensure_model() must raise."""
    import eyeclaude.eye_tracker as et

    bogus_path = tmp_path / "face_landmarker.task"
    mocker.patch.object(et, "MODEL_DIR", tmp_path)
    mocker.patch.object(et, "MODEL_PATH", bogus_path)

    def fake_download(_url, dest):
        # Write garbage — sha will not match the pinned value
        dest_path = bogus_path  # urlretrieve takes a path-like
        with open(dest_path, "wb") as f:
            f.write(b"not-the-real-model-bytes")

    mocker.patch("urllib.request.urlretrieve", side_effect=fake_download)

    import pytest
    with pytest.raises(RuntimeError, match="checksum"):
        et.ensure_model()

    assert not bogus_path.exists(), "Bad-checksum file must be deleted"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_eye_tracker.py::test_ensure_model_rejects_wrong_sha -v`
Expected: FAIL — current `ensure_model()` does no checksum check.

- [ ] **Step 4: Modify `ensure_model()` to verify SHA-256**

Replace `src/eyeclaude/eye_tracker.py:42-54` with:

```python
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
MODEL_DIR = Path.home() / ".eyeclaude"
MODEL_PATH = MODEL_DIR / "face_landmarker.task"
# Pinned SHA-256 of the float16 face_landmarker.task model.
# Paste the value computed in Step 1 here:
MODEL_SHA256 = "PASTE_HEX_DIGEST_FROM_STEP_1_HERE"


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model() -> str:
    """Download the FaceLandmarker model if not present and verify its SHA-256.

    Refuses to return a path whose checksum doesn't match MODEL_SHA256.
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not MODEL_PATH.exists():
        logger.info("Downloading FaceLandmarker model...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        logger.info("Model saved to %s", MODEL_PATH)

    actual = _sha256(MODEL_PATH)
    if actual != MODEL_SHA256:
        MODEL_PATH.unlink(missing_ok=True)
        raise RuntimeError(
            f"FaceLandmarker model checksum mismatch: "
            f"expected {MODEL_SHA256}, got {actual}. Deleted; retry."
        )
    return str(MODEL_PATH)
```

**Note for the engineer:** before committing, replace `PASTE_HEX_DIGEST_FROM_STEP_1_HERE` with the real digest you computed.

- [ ] **Step 5: Run all eye_tracker tests**

Run: `pytest tests/test_eye_tracker.py -v`
Expected: all PASS, including the new checksum-mismatch test.

- [ ] **Step 6: Commit**

```bash
git add src/eyeclaude/eye_tracker.py tests/test_eye_tracker.py
git commit -m "fix: verify MediaPipe model SHA-256 before use"
```

---

## Task 3: Eliminate shell injection in statusline installer

**Problem.** `cli.py:_install_statusline` builds a `bash -c '...'` command string by interpolating `indicator_dir_str` (a user-home path) directly. If the home path contains `'`, `;`, `$(...)`, or `\``, the resulting `statusLine.command` becomes arbitrary code that runs every time Claude Code refreshes the statusline. Even without an attacker, `$` and backticks in usernames will silently break the indicator. Fix: stop using `bash -c`; have ccstatusline composition live in a small Python entry point (`eyeclaude-statusline`) that reads stdin and the indicator file safely.

**Files:**
- Create: `src/eyeclaude/statusline_command.py`
- Modify: `src/eyeclaude/cli.py:55-93` (and `pyproject.toml` to expose new entry point)
- Test: `tests/test_statusline_command.py`

- [ ] **Step 1: Write the failing test for the composer**

Create `tests/test_statusline_command.py`:

```python
"""Tests for the eyeclaude-statusline composer."""

import io
from pathlib import Path

import pytest

from eyeclaude import statusline_command as sc


def test_compose_indicator_and_ccstatusline(tmp_path, mocker):
    """Indicator from file + ccstatusline output → 'IND CCS'."""
    indicator_file = tmp_path / "indicator"
    indicator_file.write_text("\U0001f7e2◀", encoding="utf-8")

    mocker.patch.object(sc, "_run_ccstatusline", return_value="branch | model")
    mocker.patch.object(sc, "INDICATOR_PATH", indicator_file)

    out = sc.compose(stdin_data="{\"foo\":1}")
    assert out == "\U0001f7e2◀ branch | model"


def test_compose_indicator_only_when_ccstatusline_fails(tmp_path, mocker):
    indicator_file = tmp_path / "indicator"
    indicator_file.write_text("X", encoding="utf-8")
    mocker.patch.object(sc, "_run_ccstatusline", return_value="")
    mocker.patch.object(sc, "INDICATOR_PATH", indicator_file)
    assert sc.compose(stdin_data="") == "X"


def test_compose_ccstatusline_only_when_no_indicator(tmp_path, mocker):
    indicator_file = tmp_path / "missing"
    mocker.patch.object(sc, "_run_ccstatusline", return_value="ccs-out")
    mocker.patch.object(sc, "INDICATOR_PATH", indicator_file)
    assert sc.compose(stdin_data="") == "ccs-out"


def test_compose_empty_when_neither(tmp_path, mocker):
    mocker.patch.object(sc, "_run_ccstatusline", return_value="")
    mocker.patch.object(sc, "INDICATOR_PATH", tmp_path / "missing")
    assert sc.compose(stdin_data="") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_statusline_command.py -v`
Expected: FAIL — `statusline_command` module does not exist.

- [ ] **Step 3: Create the composer module**

Create `src/eyeclaude/statusline_command.py`:

```python
"""Statusline composer entry point.

Reads stdin (the JSON Claude Code feeds to statusline commands), invokes
ccstatusline through npx, prepends an EyeClaude indicator if present, and
writes the combined line to stdout. Pure Python — no shell interpolation.
"""

import subprocess
import sys
from pathlib import Path

INDICATOR_PATH = Path.home() / ".eyeclaude" / "status" / "indicator"


def _run_ccstatusline(stdin_data: str) -> str:
    """Invoke ccstatusline via npx with stdin piped in. Returns its stdout,
    or '' if it fails for any reason."""
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

- [ ] **Step 4: Register the entry point**

Open `pyproject.toml` and find the `[project.scripts]` table. Add a new entry alongside `eyeclaude` and `eyeclaude-hooks`:

```toml
eyeclaude-statusline = "eyeclaude.statusline_command:main"
```

Re-install in editable mode so the new script is on PATH:

```bash
pip install -e .
```

- [ ] **Step 5: Run the composer tests**

Run: `pytest tests/test_statusline_command.py -v`
Expected: all PASS.

- [ ] **Step 6: Replace `_install_statusline` to call the new entry point**

In `src/eyeclaude/cli.py`, replace the body of `_install_statusline()` (lines 55–93) with:

```python
def _install_statusline():
    """Install EyeClaude indicator into Claude Code's statusline.

    Uses the `eyeclaude-statusline` console script — no shell interpolation,
    no bash dependency.
    """
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

- [ ] **Step 7: Manual smoke test**

Verify the indicator still appears in Claude Code's statusline:

```bash
eyeclaude start  # in one terminal
# In another Claude Code session, observe statusline shows: 🟢◀ <ccstatusline output>
```

Then `Ctrl+C` to stop and verify the backup restoration on shutdown works (statusline returns to its prior config).

- [ ] **Step 8: Commit**

```bash
git add src/eyeclaude/statusline_command.py src/eyeclaude/cli.py pyproject.toml tests/test_statusline_command.py
git commit -m "fix: replace shell-interpolated statusline command with python entry point"
```

---

## Task 4: hooks.py — log failures instead of silently swallowing

**Problem.** `hooks.py:67-78` catches every exception from the pipe-write path and exits 0. If EyeClaude is supposed to be running but the pipe is misconfigured, the firewall blocks it, or any other error occurs, the user has no signal — they just wonder why their statusline doesn't update. Fix: append a one-line diagnostic to `~/.eyeclaude/hooks.log` (capped at ~32 KiB to avoid unbounded growth) and still exit 0 so Claude Code itself is never blocked.

**Files:**
- Modify: `src/eyeclaude/hooks.py:67-80`
- Create: `tests/test_hooks.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hooks.py`:

```python
"""Tests for the eyeclaude-hooks CLI entry point."""

import json
import sys
from unittest.mock import MagicMock

import pytest

from eyeclaude import hooks


def test_main_writes_status_message_to_pipe(mocker, monkeypatch):
    """hooks.main() builds a status JSON and writes it to the pipe."""
    monkeypatch.setattr(sys, "argv", ["eyeclaude-hooks", "status", "working"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    mocker.patch.object(hooks, "_get_terminal_hwnd", return_value=12345)

    fake_handle = object()
    create = mocker.patch("win32file.CreateFile", return_value=fake_handle)
    write = mocker.patch("win32file.WriteFile")
    close = mocker.patch("win32file.CloseHandle")

    with pytest.raises(SystemExit) as e:
        hooks.main()
    assert e.value.code == 0

    create.assert_called_once()
    write.assert_called_once()
    payload = json.loads(write.call_args[0][1].decode("utf-8"))
    assert payload == {"type": "status", "window_handle": 12345, "state": "working"}
    close.assert_called_once_with(fake_handle)


def test_main_logs_when_pipe_write_fails(mocker, monkeypatch, tmp_path):
    """A failed pipe write must append a line to hooks.log, not silently disappear."""
    log_path = tmp_path / "hooks.log"
    monkeypatch.setattr(hooks, "LOG_PATH", log_path)

    monkeypatch.setattr(sys, "argv", ["eyeclaude-hooks", "status", "idle"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    mocker.patch.object(hooks, "_get_terminal_hwnd", return_value=999)
    mocker.patch("win32file.CreateFile", side_effect=OSError("pipe not found"))

    with pytest.raises(SystemExit) as e:
        hooks.main()
    assert e.value.code == 0  # must not propagate the error to Claude Code

    contents = log_path.read_text(encoding="utf-8")
    assert "pipe not found" in contents
    assert "idle" in contents


def test_log_file_rotates_when_too_large(monkeypatch, tmp_path):
    """If hooks.log exceeds the cap, it gets truncated before append."""
    log_path = tmp_path / "hooks.log"
    log_path.write_text("x" * (40 * 1024), encoding="utf-8")  # 40 KiB
    monkeypatch.setattr(hooks, "LOG_PATH", log_path)
    monkeypatch.setattr(hooks, "LOG_MAX_BYTES", 32 * 1024)

    hooks._log_failure("test message")

    new_size = log_path.stat().st_size
    assert new_size < 32 * 1024 + 1024, f"Log grew unbounded ({new_size} bytes)"
    assert "test message" in log_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hooks.py -v`
Expected: FAIL — `LOG_PATH`, `LOG_MAX_BYTES`, and `_log_failure` don't exist yet.

- [ ] **Step 3: Add logging to hooks.py**

Edit `src/eyeclaude/hooks.py`. After the `PIPE_NAME` constant (around line 10), add:

```python
LOG_PATH = os.path.expanduser(r"~\.eyeclaude\hooks.log")
LOG_MAX_BYTES = 32 * 1024


def _log_failure(message: str) -> None:
    """Append a diagnostic line to hooks.log; rotate if too large.

    Best-effort — if logging itself fails, we still must not block Claude Code.
    """
    try:
        from datetime import datetime
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            # Truncate; keep last half to preserve recent context
            with open(LOG_PATH, "rb") as f:
                f.seek(-(LOG_MAX_BYTES // 2), 2)
                tail = f.read()
            with open(LOG_PATH, "wb") as f:
                f.write(tail)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {message}\n")
    except Exception:
        pass
```

Then replace the silent-except block (lines 67–78) with:

```python
    try:
        handle = win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_WRITE,
            0, None,
            win32file.OPEN_EXISTING,
            0, None,
        )
        win32file.WriteFile(handle, message)
        win32file.CloseHandle(handle)
    except Exception as e:
        _log_failure(f"pipe write failed (state={state}, hwnd={hwnd}): {e}")
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/test_hooks.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/hooks.py tests/test_hooks.py
git commit -m "fix: log hook pipe-write failures to ~/.eyeclaude/hooks.log"
```

---

## Task 5: Prune dead terminals from SharedState

**Problem.** When a terminal window closes, nothing tells EyeClaude. The HWND remains registered, `state.get_terminal_for_quadrant()` may return it, and `window_manager.update_focus()` calls `SetForegroundWindow` on a dead handle. Fix: in the main loop, periodically iterate registered terminals and unregister any whose HWND is no longer a valid window (`win32gui.IsWindow`).

**Files:**
- Read first: `src/eyeclaude/shared_state.py` — confirm the unregister API. If only `unregister_terminal(pid=...)` exists, the existing call works (HWND is used as PID per `cli.py:194`). If not, add `unregister_terminal_by_hwnd`.
- Modify: `src/eyeclaude/cli.py` main loop (after `~line 338`)
- Test: `tests/test_integration.py` (add)

- [ ] **Step 1: Verify SharedState's unregister API**

Run: `grep -n "def unregister" src/eyeclaude/shared_state.py`

Expected: see one or more methods. Note the exact signature. If `unregister_terminal(pid=...)` exists and the codebase uses HWND-as-PID (confirmed by `cli.py:194` — `pid=t.hwnd`), use it directly. **The rest of the task assumes that signature; adjust if reality differs.**

- [ ] **Step 2: Write the failing test**

Add to `tests/test_integration.py`:

```python
def test_main_loop_prunes_closed_terminals(mocker):
    """A registered terminal whose HWND is no longer a valid window must be
    unregistered when _prune_dead_terminals runs."""
    from eyeclaude.shared_state import SharedState, Quadrant
    from eyeclaude.cli import _prune_dead_terminals

    state = SharedState()
    state.register_terminal(pid=111, window_handle=111, quadrant=Quadrant.TOP_LEFT)
    state.register_terminal(pid=222, window_handle=222, quadrant=Quadrant.TOP_RIGHT)

    # HWND 111 is "closed", HWND 222 still alive.
    def is_window(hwnd):
        return hwnd == 222
    mocker.patch("win32gui.IsWindow", side_effect=is_window)

    _prune_dead_terminals(state)

    remaining = [t.window_handle for t in state.get_all_terminals()]
    assert remaining == [222]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_integration.py::test_main_loop_prunes_closed_terminals -v`
Expected: FAIL — `_prune_dead_terminals` doesn't exist.

- [ ] **Step 4: Add the prune helper**

In `src/eyeclaude/cli.py`, just before the `@main.command()` line for `start` (~line 156), add:

```python
def _prune_dead_terminals(state: SharedState) -> None:
    """Remove terminals whose window handles are no longer valid windows.

    Called periodically from the main loop to keep state.get_all_terminals()
    free of HWNDs belonging to terminals the user has closed.
    """
    try:
        import win32gui
    except ImportError:
        return
    for terminal in list(state.get_all_terminals()):
        if not win32gui.IsWindow(terminal.window_handle):
            state.unregister_terminal(pid=terminal.pid)
            logger.info("Pruned dead terminal hwnd=%s", terminal.window_handle)
```

- [ ] **Step 5: Wire it into the main loop**

In `src/eyeclaude/cli.py`, find the main loop body (around line 269–340). Locate the `if paused:` / `else:` branch around line 315. After the `_update_active_status_files(state)` call (~line 339), add a throttled prune:

```python
                _update_active_status_files(state)
                # Throttle prune to once every ~2 seconds (loop runs every 50ms)
                if not hasattr(_prune_dead_terminals, "_tick"):
                    _prune_dead_terminals._tick = 0
                _prune_dead_terminals._tick += 1
                if _prune_dead_terminals._tick >= 40:
                    _prune_dead_terminals._tick = 0
                    _prune_dead_terminals(state)
```

- [ ] **Step 6: Run the test**

Run: `pytest tests/test_integration.py::test_main_loop_prunes_closed_terminals -v`
Expected: PASS.

Then run the full suite as a sanity check:

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/eyeclaude/cli.py tests/test_integration.py
git commit -m "fix: prune dead terminals from shared state in main loop"
```

---

## Task 6: Final verification

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: all PASS, no warnings about the new code.

- [ ] **Step 2: Manual end-to-end smoke test**

Open two Windows Terminal windows on different monitors (if available), then:

```bash
eyeclaude start
```

Verify:
- Calibration overlay opens and 5-point calibration completes.
- Terminals on the secondary monitor get correct quadrants (Task 1).
- Statusline indicator appears in Claude Code without backtick/dollar errors (Task 3).
- Close one terminal mid-session, wait ~3 seconds, verify it disappears from `~/.eyeclaude/status/` and focus no longer targets it (Task 5).
- Trigger a hook with EyeClaude stopped (start a Claude Code session without `eyeclaude start`), then check `~/.eyeclaude/hooks.log` contains a "pipe write failed" line (Task 4).

- [ ] **Step 3: Commit any final fixes**

If smoke test reveals integration issues, fix and commit. If clean:

```bash
git log --oneline -8
```

Expected: 5 new commits matching the task headings.

---

## Self-Review Notes

- **Spec coverage:** Six critical issues from the analysis (multi-monitor, model checksum, shell injection, silent hook failures, stale terminals, hooks test gap) — each maps to exactly one task. Deferred items called out in the goal section.
- **Placeholders:** One intentional placeholder remains — `MODEL_SHA256` in Task 2 must be filled with the digest the engineer computes in Step 1 of that task. This is unavoidable: the plan author cannot run `Get-FileHash` against the user's local model. Engineer instructions are explicit.
- **Type consistency:** `_assign_quadrant_by_position`, `_prune_dead_terminals`, `_log_failure`, `LOG_PATH`, `LOG_MAX_BYTES`, `compose`, `_run_ccstatusline`, `INDICATOR_PATH` — all names referenced consistently in tests and impl.
