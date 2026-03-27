"""Transparent click-through overlay for drawing colored borders around quadrants."""

import ctypes
import ctypes.wintypes
import logging
import threading
import time

import win32api
import win32con
import win32gui

from eyeclaude.shared_state import Quadrant, InstanceStatus, SharedState

logger = logging.getLogger(__name__)

TRANSPARENT_COLOR = win32api.RGB(255, 0, 255)  # Magenta = transparent
WM_USER_UPDATE = win32con.WM_USER + 1
PS_INSIDEFRAME = 6
NULL_BRUSH = 5


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


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to (R, G, B)."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _status_to_color(
    status: InstanceStatus, border_colors: dict[str, str], pulse_phase: float
) -> int:
    """Convert status to a win32 RGB color value."""
    if status == InstanceStatus.WORKING:
        # Pulsing blue: oscillate brightness
        r, g, b = _hex_to_rgb(border_colors["working"])
        factor = 0.5 + 0.5 * abs((pulse_phase % 1.0) * 2 - 1)
        return win32api.RGB(int(r * factor), int(g * factor), int(b * factor))

    color_key = {
        InstanceStatus.IDLE: "idle",
        InstanceStatus.FINISHED: "finished",
        InstanceStatus.ERROR: "error",
    }.get(status, "idle")

    r, g, b = _hex_to_rgb(border_colors[color_key])
    return win32api.RGB(r, g, b)


class Overlay:
    """Transparent, click-through, always-on-top overlay that draws colored borders."""

    CLASS_NAME = "EyeClaudeOverlay"

    def __init__(self, state: SharedState, border_colors: dict[str, str], border_thickness: int = 4):
        self._state = state
        self._border_colors = border_colors
        self._border_thickness = border_thickness
        self._hwnd = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._running = False
        self._pulse_phase = 0.0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        self._running = False
        if self._hwnd:
            win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(timeout=3)

    def request_repaint(self) -> None:
        if self._hwnd:
            win32gui.PostMessage(self._hwnd, WM_USER_UPDATE, 0, 0)

    def _run(self) -> None:
        hinstance = win32api.GetModuleHandle(None)

        wc = win32gui.WNDCLASS()
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wc.lpfnWndProc = self._wnd_proc
        wc.hInstance = hinstance
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32gui.GetStockObject(NULL_BRUSH)
        wc.lpszClassName = self.CLASS_NAME

        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass

        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        ex_style = (
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOPMOST
            | win32con.WS_EX_TOOLWINDOW
        )

        self._hwnd = win32gui.CreateWindowEx(
            ex_style,
            self.CLASS_NAME,
            "EyeClaude Overlay",
            win32con.WS_POPUP,
            0, 0, screen_w, screen_h,
            0, 0, hinstance, None,
        )

        win32gui.SetLayeredWindowAttributes(
            self._hwnd, TRANSPARENT_COLOR, 0, win32con.LWA_COLORKEY,
        )

        win32gui.ShowWindow(self._hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.UpdateWindow(self._hwnd)

        # Set a timer for periodic repaint (for pulsing animation + state updates)
        TIMER_ID = 1
        ctypes.windll.user32.SetTimer(self._hwnd, TIMER_ID, 50, None)  # 50ms = 20fps

        self._ready.set()

        msg = ctypes.wintypes.MSG()
        while self._running:
            result = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if result <= 0:
                break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_PAINT:
            self._on_paint(hwnd)
            return 0

        if msg == WM_USER_UPDATE or msg == win32con.WM_TIMER:
            self._pulse_phase += 0.05
            win32gui.InvalidateRect(hwnd, None, True)
            return 0

        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_paint(self, hwnd):
        hdc, ps = win32gui.BeginPaint(hwnd)
        rect = win32gui.GetClientRect(hwnd)
        screen_w = rect[2]
        screen_h = rect[3]

        # Fill with transparent color
        brush = win32gui.CreateSolidBrush(TRANSPARENT_COLOR)
        win32gui.FillRect(hdc, rect, brush)
        win32gui.DeleteObject(brush)

        # Draw borders for all registered terminals
        old_brush = win32gui.SelectObject(hdc, win32gui.GetStockObject(NULL_BRUSH))

        active_quadrant = self._state.active_quadrant
        terminals = self._state.get_all_terminals()

        for terminal in terminals:
            x, y, w, h = compute_quadrant_rect(terminal.quadrant, screen_w, screen_h)
            color = _status_to_color(
                terminal.status, self._border_colors, self._pulse_phase
            )
            # Active quadrant gets full thickness, inactive gets thinner border
            thickness = self._border_thickness if terminal.quadrant == active_quadrant else max(1, self._border_thickness // 2)
            pen = win32gui.CreatePen(PS_INSIDEFRAME, thickness, color)
            old_pen = win32gui.SelectObject(hdc, pen)
            win32gui.Rectangle(hdc, x, y, x + w, y + h)
            win32gui.SelectObject(hdc, old_pen)
            win32gui.DeleteObject(pen)

        win32gui.SelectObject(hdc, old_brush)
        win32gui.EndPaint(hwnd, ps)
