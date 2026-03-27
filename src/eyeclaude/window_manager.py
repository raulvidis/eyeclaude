"""Win32 window focus management."""

import logging

import win32gui
import win32con

from eyeclaude.shared_state import SharedState, Quadrant

logger = logging.getLogger(__name__)


def set_foreground_window(hwnd: int) -> None:
    """Attempt to bring a window to the foreground."""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        logger.warning("Failed to set foreground window %d: %s", hwnd, e)


class WindowManager:
    """Manages focus switching between registered terminal windows."""

    def __init__(self, state: SharedState):
        self._state = state
        self._current_quadrant: Quadrant | None = None

    def update_focus(self, quadrant: Quadrant | None) -> None:
        """Switch focus to the terminal in the given quadrant, if different from current."""
        if quadrant is None:
            return

        if quadrant == self._current_quadrant:
            return

        terminal = self._state.get_terminal_for_quadrant(quadrant)
        if terminal is None:
            return

        self._current_quadrant = quadrant
        set_foreground_window(terminal.window_handle)
        logger.debug("Focused quadrant %s (hwnd=%d)", quadrant.value, terminal.window_handle)
