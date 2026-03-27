# src/eyeclaude/calibration_overlay.py
"""Full-screen Tkinter calibration overlay with live gaze pointer."""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TerminalRect:
    hwnd: int
    label: str
    left: int
    top: int
    right: int
    bottom: int

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


class CalibrationState:
    def __init__(self):
        self.selected_hwnd: int | None = None
        self.recording: bool = False
        self.samples: list[tuple[float, float]] = []
        self.calibrated_hwnds: set[int] = set()

    def select(self, hwnd: int) -> None:
        self.selected_hwnd = hwnd
        self.recording = False
        self.samples = []

    def start_recording(self) -> None:
        self.recording = True
        self.samples = []

    def add_sample(self, x: float, y: float) -> None:
        if self.recording:
            self.samples.append((x, y))

    def stop_recording(self) -> list[tuple[float, float]]:
        if not self.recording:
            return []
        self.recording = False
        result = list(self.samples)
        if self.selected_hwnd is not None:
            self.calibrated_hwnds.add(self.selected_hwnd)
        return result
