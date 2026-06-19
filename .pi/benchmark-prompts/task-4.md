Task 4: hooks.py — log failures instead of silently swallowing

Problem: `hooks.py` silently exits 0 if the pipe write fails. Fix: append a rotated diagnostic line to `~/.eyeclaude/hooks.log`.

Files:
- Modify: src/eyeclaude/hooks.py
- Create: tests/test_hooks.py

Step 1 — Create `tests/test_hooks.py`:

```python
"""Tests for the eyeclaude-hooks CLI entry point."""

import json
import sys

import pytest

from eyeclaude import hooks


def test_main_writes_status_message_to_pipe(mocker, monkeypatch):
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
    log_path = tmp_path / "hooks.log"
    monkeypatch.setattr(hooks, "LOG_PATH", log_path)

    monkeypatch.setattr(sys, "argv", ["eyeclaude-hooks", "status", "idle"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    mocker.patch.object(hooks, "_get_terminal_hwnd", return_value=999)
    mocker.patch("win32file.CreateFile", side_effect=OSError("pipe not found"))

    with pytest.raises(SystemExit) as e:
        hooks.main()
    assert e.value.code == 0

    contents = log_path.read_text(encoding="utf-8")
    assert "pipe not found" in contents
    assert "idle" in contents


def test_log_file_rotates_when_too_large(monkeypatch, tmp_path):
    log_path = tmp_path / "hooks.log"
    log_path.write_text("x" * (40 * 1024), encoding="utf-8")
    monkeypatch.setattr(hooks, "LOG_PATH", log_path)
    monkeypatch.setattr(hooks, "LOG_MAX_BYTES", 32 * 1024)

    hooks._log_failure("test message")

    new_size = log_path.stat().st_size
    assert new_size < 32 * 1024 + 1024, f"Log grew unbounded ({new_size} bytes)"
    assert "test message" in log_path.read_text(encoding="utf-8")
```

Step 2 — Run `pytest tests/test_hooks.py -v`. Expected: FAIL.

Step 3 — Edit `src/eyeclaude/hooks.py`. After the `PIPE_NAME = ...` line near the top, add:

```python
LOG_PATH = os.path.expanduser(r"~\.eyeclaude\hooks.log")
LOG_MAX_BYTES = 32 * 1024


def _log_failure(message: str) -> None:
    """Append a diagnostic line to hooks.log; rotate if too large."""
    try:
        from datetime import datetime
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
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

Step 4 — In the same file, find the `try/except` around `win32file.CreateFile` / `WriteFile` / `CloseHandle`. Replace the `except Exception: pass` with:

```python
    except Exception as e:
        _log_failure(f"pipe write failed (state={state}, hwnd={hwnd}): {e}")
```

Step 5 — Run `pytest tests/test_hooks.py -v`. All 3 tests must pass.

Step 6 — Commit:
```
git add src/eyeclaude/hooks.py tests/test_hooks.py
git commit -m "fix: log hook pipe-write failures to ~/.eyeclaude/hooks.log"
```

Then reply "Task 4 done." and stop.
