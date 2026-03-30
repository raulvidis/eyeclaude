"""Win32 window focus management."""

import logging

import win32api
import win32con
import win32gui
import win32process

from eyeclaude.shared_state import SharedState, Quadrant

logger = logging.getLogger(__name__)


def set_foreground_window(hwnd: int) -> None:
    """Bring a window to the foreground with full keyboard focus.

    Uses AttachThreadInput to temporarily attach to the target window's
    thread, which allows SetForegroundWindow to grant keyboard focus
    even when coming back from a different application/monitor.
    """
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        # Attach our thread to the target window's thread so Windows
        # allows us to steal focus and grant keyboard input
        current_thread = win32api.GetCurrentThreadId()
        target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)

        if current_thread != target_thread:
            win32process.AttachThreadInput(current_thread, target_thread, True)
            try:
                win32gui.SetForegroundWindow(hwnd)
            finally:
                win32process.AttachThreadInput(current_thread, target_thread, False)
        else:
            win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        logger.warning("Failed to set foreground window %d: %s", hwnd, e)


class WindowManager:
    """Manages focus switching between registered terminal windows."""

    def __init__(self, state: SharedState):
        self._state = state
        self._current_quadrant: Quadrant | None = None

    def is_registered_window_focused(self) -> bool:
        """Check if any registered terminal window currently has focus."""
        try:
            fg_hwnd = win32gui.GetForegroundWindow()
            terminals = self._state.get_all_terminals()
            return any(t.window_handle == fg_hwnd for t in terminals)
        except Exception:
            return False

    def update_focus(self, quadrant: Quadrant | None) -> None:
        """Switch focus to the terminal in the given quadrant, if different from current.

        The dwell tracker (400ms) already prevents accidental switches,
        so we don't block on unregistered windows — this allows focus to
        resume when returning from another monitor or app.
        """
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
