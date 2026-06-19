Task 1: Multi-monitor quadrant logic

Problem: `pipe_server.py:_assign_quadrant_by_position` uses `GetSystemMetrics(0/1)` which returns the PRIMARY monitor's size. Windows on a second monitor get classified wrongly. Fix: use `MonitorFromWindow` + `GetMonitorInfo` to quadrant the window inside its OWN monitor.

Files:
- Modify: src/eyeclaude/pipe_server.py (the `_assign_quadrant_by_position` function)
- Test: tests/test_pipe_server.py (APPEND a new test)

Step 1 — Append this test to `tests/test_pipe_server.py`:

```python
def test_assign_quadrant_uses_window_monitor_not_primary_screen(mocker):
    """A window on a secondary monitor should be quadranted within that monitor's
    work area, not against the primary screen's resolution."""
    from eyeclaude.pipe_server import _assign_quadrant_by_position
    from eyeclaude.shared_state import Quadrant

    mocker.patch("win32gui.GetWindowRect", return_value=(2400, 100, 3200, 600))
    mocker.patch("win32api.MonitorFromWindow", return_value=12345)
    mocker.patch(
        "win32api.GetMonitorInfo",
        return_value={"Work": (1920, 0, 3840, 1080), "Monitor": (1920, 0, 3840, 1080)},
    )
    # Center (2800, 350) in work area 1920..3840 x 0..1080:
    # mid_x = 2880 -> 2800 < mid_x -> LEFT; mid_y = 540 -> 350 < mid_y -> TOP
    assert _assign_quadrant_by_position(99) == Quadrant.TOP_LEFT
```

Step 2 — Run `pytest tests/test_pipe_server.py::test_assign_quadrant_uses_window_monitor_not_primary_screen -v`. Expected: FAIL.

Step 3 — Replace the body of `_assign_quadrant_by_position` in `src/eyeclaude/pipe_server.py` with:

```python
def _assign_quadrant_by_position(window_handle: int) -> Quadrant:
    """Determine which quadrant a window occupies within ITS OWN monitor.

    Uses MonitorFromWindow to find the monitor hosting the window, then
    quadrants the window's center against that monitor's work area.
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

Step 4 — Run `pytest tests/test_pipe_server.py -v`. All tests must pass.

Step 5 — Commit:
```
git add src/eyeclaude/pipe_server.py tests/test_pipe_server.py
git commit -m "fix: quadrant assignment uses window's own monitor work area"
```

Then reply "Task 1 done." and stop.
