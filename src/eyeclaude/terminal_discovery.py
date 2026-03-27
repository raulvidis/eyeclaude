# src/eyeclaude/terminal_discovery.py
"""Auto-detection of Windows Terminal windows."""

import logging
from dataclasses import dataclass

import win32gui

logger = logging.getLogger(__name__)

TERMINAL_CLASS_NAMES = {"CASCADIA_HOSTING_WINDOW_CLASS"}


@dataclass
class DiscoveredTerminal:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)


def discover_terminals() -> list[DiscoveredTerminal]:
    """Find all visible Windows Terminal windows on screen."""
    terminals: list[DiscoveredTerminal] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        class_name = win32gui.GetClassName(hwnd)
        if class_name not in TERMINAL_CLASS_NAMES:
            return True
        try:
            rect = win32gui.GetWindowRect(hwnd)
            title = win32gui.GetWindowText(hwnd)
            terminals.append(DiscoveredTerminal(hwnd=hwnd, title=title, rect=rect))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)
    return terminals


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Get the current screen rect for a window handle. Returns None if invalid."""
    try:
        return win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
