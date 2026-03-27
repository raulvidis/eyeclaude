"""Terminal title-based status indicator for EyeClaude."""

import logging

import win32gui

from eyeclaude.shared_state import Quadrant, InstanceStatus, SharedState

logger = logging.getLogger(__name__)

STATUS_PREFIX = {
    InstanceStatus.IDLE: "\U0001f7e2",      # 🟢
    InstanceStatus.WORKING: "\U0001f535",    # 🔵
    InstanceStatus.FINISHED: "\U0001f7e1",   # 🟡
    InstanceStatus.ERROR: "\U0001f534",      # 🔴
}

ACTIVE_INDICATOR = "\u25c0"  # ◀ — shows which terminal has eye-focus


def compute_quadrant_rect(
    quadrant: Quadrant, screen_w: int, screen_h: int
) -> tuple[int, int, int, int]:
    """Return (x, y, width, height) for a quadrant."""
    half_w = screen_w // 2
    half_h = screen_h // 2
    rects = {
        Quadrant.TOP_LEFT: (0, 0, half_w, half_h),
        Quadrant.TOP_RIGHT: (half_w, 0, screen_w - half_w, half_h),
        Quadrant.BOTTOM_LEFT: (0, half_h, half_w, screen_h - half_h),
        Quadrant.BOTTOM_RIGHT: (half_w, half_h, screen_w - half_w, screen_h - half_h),
    }
    return rects[quadrant]


class Overlay:
    """Updates terminal window titles to show Claude Code status and eye-focus."""

    def __init__(self, state: SharedState, border_colors: dict[str, str] = None, border_thickness: int = 4):
        self._state = state
        # Track original titles so we can restore them on stop
        self._original_titles: dict[int, str] = {}
        self._last_titles: dict[int, str] = {}

    def start(self) -> None:
        """Capture original window titles."""
        for terminal in self._state.get_all_terminals():
            try:
                title = win32gui.GetWindowText(terminal.window_handle)
                self._original_titles[terminal.window_handle] = title
            except Exception:
                pass

    def stop(self) -> None:
        """Restore original window titles."""
        for hwnd, title in self._original_titles.items():
            try:
                win32gui.SetWindowText(hwnd, title)
            except Exception:
                pass

    def update(self) -> None:
        """Update all terminal window titles based on current status and active quadrant."""
        active_quadrant = self._state.active_quadrant
        terminals = self._state.get_all_terminals()

        for terminal in terminals:
            hwnd = terminal.window_handle

            # Capture original title if we haven't yet
            if hwnd not in self._original_titles:
                try:
                    self._original_titles[hwnd] = win32gui.GetWindowText(hwnd)
                except Exception:
                    self._original_titles[hwnd] = ""

            # Build the new title
            prefix = STATUS_PREFIX.get(terminal.status, STATUS_PREFIX[InstanceStatus.IDLE])
            active = f" {ACTIVE_INDICATOR}" if terminal.quadrant == active_quadrant else ""
            status_text = terminal.status.value.upper()
            new_title = f"{prefix}{active} {status_text}"

            # Only update if changed (avoid flicker)
            if self._last_titles.get(hwnd) != new_title:
                try:
                    win32gui.SetWindowText(hwnd, new_title)
                    self._last_titles[hwnd] = new_title
                except Exception as e:
                    logger.debug("Failed to set title for hwnd=%d: %s", hwnd, e)

    def request_repaint(self) -> None:
        """Compatibility method — triggers an update."""
        self.update()
