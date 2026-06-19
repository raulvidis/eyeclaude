Task 5: Prune dead terminals from SharedState

Problem: When a terminal window closes, its HWND remains in SharedState forever. Focus calls to dead handles silently no-op. Fix: a helper in cli.py that uses `win32gui.IsWindow` to remove closed windows, called every ~2 seconds from the main loop.

CRITICAL: this codebase registers terminals with `pid=hwnd` (see `cli.py:189`). The PID field holds a window handle. Do NOT use `psutil.pid_exists` or anything that treats it as an OS process ID — the only correct liveness check is `win32gui.IsWindow(window_handle)`.

Files:
- Modify: src/eyeclaude/cli.py (add the helper function AND wire it into the main loop)
- Test: tests/test_integration.py (APPEND a new test)

Step 1 — Confirm the unregister API exists:
```
grep -n "def unregister_terminal" src/eyeclaude/shared_state.py
```
Confirm the signature is `unregister_terminal(self, pid: int)`. If it differs, stop and report.

Step 2 — Append this test to `tests/test_integration.py`:

```python
def test_main_loop_prunes_closed_terminals(mocker):
    """A registered terminal whose HWND is no longer a valid window must be
    unregistered when _prune_dead_terminals runs."""
    from eyeclaude.shared_state import SharedState, Quadrant
    from eyeclaude.cli import _prune_dead_terminals

    state = SharedState()
    state.register_terminal(pid=111, window_handle=111, quadrant=Quadrant.TOP_LEFT)
    state.register_terminal(pid=222, window_handle=222, quadrant=Quadrant.TOP_RIGHT)

    mocker.patch("win32gui.IsWindow", side_effect=lambda h: h == 222)

    _prune_dead_terminals(state)

    remaining = [t.window_handle for t in state.get_all_terminals()]
    assert remaining == [222]
```

Step 3 — Run `pytest tests/test_integration.py::test_main_loop_prunes_closed_terminals -v`. Expected: FAIL.

Step 4 — Add this helper to `src/eyeclaude/cli.py`, at the bottom of the file, right BEFORE `if __name__ == "__main__":`:

```python
def _prune_dead_terminals(state: SharedState) -> None:
    """Remove terminals whose window handles are no longer valid windows."""
    try:
        import win32gui
    except ImportError:
        return
    for terminal in list(state.get_all_terminals()):
        if not win32gui.IsWindow(terminal.window_handle):
            state.unregister_terminal(pid=terminal.pid)
            logger.info("Pruned dead terminal hwnd=%s", terminal.window_handle)
```

Step 5 — Wire it into the main loop. In `src/eyeclaude/cli.py`, find the `start()` function's main loop. Inside the `else:` branch (the non-paused path), find the line `_update_active_status_files(state)`. Right AFTER that line, add (matching the indentation):

```python
                # Throttle prune to once every ~2 seconds (loop runs every 50ms)
                if not hasattr(_prune_dead_terminals, "_tick"):
                    _prune_dead_terminals._tick = 0
                _prune_dead_terminals._tick += 1
                if _prune_dead_terminals._tick >= 40:
                    _prune_dead_terminals._tick = 0
                    _prune_dead_terminals(state)
```

Step 6 — Run `pytest -v` (full suite). All tests must pass.

Step 7 — Commit:
```
git add src/eyeclaude/cli.py tests/test_integration.py
git commit -m "fix: prune dead terminals from shared state in main loop"
```

Then reply "Task 5 done." and stop.
