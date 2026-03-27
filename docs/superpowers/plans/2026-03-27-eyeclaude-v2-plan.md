# EyeClaude v2 Registration & Calibration Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual `/eyeclaude-register` with auto-discovery of terminals, a visual Tkinter calibration overlay with live gaze pointer, and status indicators in Claude Code's statusline instead of window title hacking.

**Architecture:** Auto-discovery finds terminal windows via Win32 EnumWindows. A full-screen Tkinter overlay shows terminal rectangles (updating positions in real-time) with a live gaze dot. User clicks a terminal, presses Start/End to record calibration samples. Status moves from window titles to a statusline wrapper that reads per-terminal JSON files written by the pipe server.

**Tech Stack:** Python 3.13, Tkinter (stdlib), MediaPipe, OpenCV, pywin32, Click, numpy

---

### Task 1: Terminal Discovery Module

**Files:**
- Create: `src/eyeclaude/terminal_discovery.py`
- Create: `tests/test_terminal_discovery.py`

- [ ] **Step 1: Write failing tests for terminal discovery**

```python
# tests/test_terminal_discovery.py
"""Tests for terminal auto-discovery."""

import pytest
from unittest.mock import patch, MagicMock

from eyeclaude.terminal_discovery import discover_terminals, get_window_rect, DiscoveredTerminal


class TestDiscoverTerminals:
    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_finds_cascadia_windows(self, mock_gui):
        """EnumWindows finds visible CASCADIA windows."""
        mock_gui.IsWindowVisible.return_value = True
        mock_gui.GetClassName.return_value = "CASCADIA_HOSTING_WINDOW_CLASS"
        mock_gui.GetWindowRect.return_value = (0, 0, 960, 540)
        mock_gui.GetWindowText.return_value = "Windows Terminal"

        # Simulate EnumWindows calling our callback with two HWNDs
        def fake_enum(callback, _):
            callback(1001, None)
            callback(1002, None)
            return True
        mock_gui.EnumWindows.side_effect = fake_enum

        result = discover_terminals()
        assert len(result) == 2
        assert result[0].hwnd == 1001
        assert result[1].hwnd == 1002

    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_skips_invisible_windows(self, mock_gui):
        """Invisible windows are ignored."""
        mock_gui.IsWindowVisible.return_value = False
        mock_gui.GetClassName.return_value = "CASCADIA_HOSTING_WINDOW_CLASS"

        def fake_enum(callback, _):
            callback(1001, None)
            return True
        mock_gui.EnumWindows.side_effect = fake_enum

        result = discover_terminals()
        assert len(result) == 0

    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_skips_non_terminal_windows(self, mock_gui):
        """Non-terminal windows are ignored."""
        mock_gui.IsWindowVisible.return_value = True
        mock_gui.GetClassName.return_value = "Chrome_WidgetWin_1"

        def fake_enum(callback, _):
            callback(1001, None)
            return True
        mock_gui.EnumWindows.side_effect = fake_enum

        result = discover_terminals()
        assert len(result) == 0


class TestGetWindowRect:
    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_returns_rect(self, mock_gui):
        mock_gui.GetWindowRect.return_value = (100, 200, 500, 700)
        rect = get_window_rect(1001)
        assert rect == (100, 200, 500, 700)

    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_returns_none_on_invalid_hwnd(self, mock_gui):
        mock_gui.GetWindowRect.side_effect = Exception("Invalid handle")
        rect = get_window_rect(9999)
        assert rect is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest tests/test_terminal_discovery.py -v`
Expected: FAIL — module `eyeclaude.terminal_discovery` does not exist

- [ ] **Step 3: Implement terminal_discovery.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest tests/test_terminal_discovery.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
git add src/eyeclaude/terminal_discovery.py tests/test_terminal_discovery.py
git commit -m "feat: add terminal auto-discovery module"
```

---

### Task 2: Calibration Overlay — Window & Rectangle Rendering

**Files:**
- Create: `src/eyeclaude/calibration_overlay.py`
- Create: `tests/test_calibration_overlay.py`

- [ ] **Step 1: Write failing tests for overlay geometry and state**

```python
# tests/test_calibration_overlay.py
"""Tests for calibration overlay logic (non-GUI)."""

import pytest
from eyeclaude.calibration_overlay import CalibrationState, TerminalRect


class TestTerminalRect:
    def test_contains_point_inside(self):
        rect = TerminalRect(hwnd=1, label="T1", left=100, top=100, right=500, bottom=400)
        assert rect.contains(300, 250)

    def test_contains_point_outside(self):
        rect = TerminalRect(hwnd=1, label="T1", left=100, top=100, right=500, bottom=400)
        assert not rect.contains(50, 50)

    def test_contains_point_on_edge(self):
        rect = TerminalRect(hwnd=1, label="T1", left=100, top=100, right=500, bottom=400)
        assert rect.contains(100, 100)


class TestCalibrationState:
    def test_initial_state(self):
        state = CalibrationState()
        assert state.selected_hwnd is None
        assert state.recording is False
        assert state.calibrated_hwnds == set()

    def test_select_terminal(self):
        state = CalibrationState()
        state.select(hwnd=1001)
        assert state.selected_hwnd == 1001
        assert state.recording is False

    def test_start_recording(self):
        state = CalibrationState()
        state.select(hwnd=1001)
        state.start_recording()
        assert state.recording is True
        assert len(state.samples) == 0

    def test_add_sample(self):
        state = CalibrationState()
        state.select(hwnd=1001)
        state.start_recording()
        state.add_sample(0.5, 0.3)
        assert len(state.samples) == 1
        assert state.samples[0] == (0.5, 0.3)

    def test_stop_recording_returns_samples(self):
        state = CalibrationState()
        state.select(hwnd=1001)
        state.start_recording()
        state.add_sample(0.5, 0.3)
        state.add_sample(0.6, 0.4)
        samples = state.stop_recording()
        assert len(samples) == 2
        assert state.recording is False
        assert 1001 in state.calibrated_hwnds

    def test_stop_recording_without_start(self):
        state = CalibrationState()
        samples = state.stop_recording()
        assert samples == []

    def test_cannot_add_sample_when_not_recording(self):
        state = CalibrationState()
        state.add_sample(0.5, 0.3)
        assert len(state.samples) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest tests/test_calibration_overlay.py -v`
Expected: FAIL — module `eyeclaude.calibration_overlay` does not exist

- [ ] **Step 3: Implement CalibrationState and TerminalRect (data classes only, no Tkinter yet)**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest tests/test_calibration_overlay.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
git add src/eyeclaude/calibration_overlay.py tests/test_calibration_overlay.py
git commit -m "feat: add calibration overlay state and geometry classes"
```

---

### Task 3: Calibration Overlay — Tkinter GUI

**Files:**
- Modify: `src/eyeclaude/calibration_overlay.py`

This task adds the Tkinter GUI to the existing data classes. It cannot be unit-tested (requires display), so we test manually.

- [ ] **Step 1: Add the CalibrationOverlay class to calibration_overlay.py**

Append the following to the end of `src/eyeclaude/calibration_overlay.py`:

```python
import threading
import tkinter as tk
import numpy as np

from eyeclaude.terminal_discovery import discover_terminals, get_window_rect, DiscoveredTerminal
from eyeclaude.eye_tracker import CalibrationData, _get_iris_center, ensure_model


class CalibrationOverlay:
    """Full-screen Tkinter overlay for visual calibration.

    Shows discovered terminal positions as clickable rectangles with a live
    gaze pointer. User clicks a terminal, presses Start to record, moves
    eyes around the terminal, presses End to stop. Rectangles update in
    real-time if windows are moved.
    """

    GAZE_DOT_RADIUS = 10
    BG_OPACITY = 0.7
    POLL_INTERVAL_MS = 100  # Window position polling
    GAZE_INTERVAL_MS = 33   # ~30fps gaze updates

    def __init__(self, webcam_index: int = 0):
        self._webcam_index = webcam_index
        self._state = CalibrationState()
        self._terminal_rects: list[TerminalRect] = []
        self._calibration_results: dict[int, tuple[float, float]] = {}  # hwnd -> (median_x, median_y)
        self._gaze_pos: tuple[float, float] | None = None  # Screen-space gaze position
        self._running = False
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._gaze_dot_id: int | None = None
        self._status_label_id: int | None = None
        self._rect_ids: dict[int, int] = {}  # hwnd -> canvas rect id
        self._label_ids: dict[int, int] = {}  # hwnd -> canvas label id
        self._check_ids: dict[int, int] = {}  # hwnd -> canvas checkmark id

        # Gaze tracking thread
        self._gaze_thread: threading.Thread | None = None
        self._gaze_lock = threading.Lock()

    def run(self) -> CalibrationData | None:
        """Open the overlay, run calibration, return results. Blocks until closed."""
        self._running = True

        # Discover terminals
        discovered = discover_terminals()
        if not discovered:
            logger.warning("No terminal windows found")
            return None

        self._terminal_rects = [
            TerminalRect(
                hwnd=t.hwnd, label=f"Terminal {i+1}",
                left=t.rect[0], top=t.rect[1], right=t.rect[2], bottom=t.rect[3],
            )
            for i, t in enumerate(discovered)
        ]

        # Start gaze tracking thread
        self._gaze_thread = threading.Thread(target=self._gaze_loop, daemon=True)
        self._gaze_thread.start()

        # Build and run Tkinter
        self._build_gui()
        self._root.mainloop()

        # Cleanup
        self._running = False

        # Convert results to CalibrationData using quadrant assignment
        return self._build_calibration_data()

    def _build_gui(self) -> None:
        self._root = tk.Tk()
        self._root.title("EyeClaude Calibration")
        self._root.attributes("-fullscreen", True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", self.BG_OPACITY)
        self._root.configure(bg="black")

        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()

        self._canvas = tk.Canvas(
            self._root, width=screen_w, height=screen_h,
            bg="black", highlightthickness=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Draw terminal rectangles
        for tr in self._terminal_rects:
            rid = self._canvas.create_rectangle(
                tr.left, tr.top, tr.right, tr.bottom,
                outline="white", width=3, fill="",
            )
            self._rect_ids[tr.hwnd] = rid

            cx = (tr.left + tr.right) // 2
            cy = (tr.top + tr.bottom) // 2
            lid = self._canvas.create_text(
                cx, cy, text=tr.label, fill="white",
                font=("Segoe UI", 16, "bold"),
            )
            self._label_ids[tr.hwnd] = lid

        # Instructions
        self._canvas.create_text(
            screen_w // 2, 30,
            text="Click a terminal to select it · Press S to Start recording · Press E to End recording · ESC to finish",
            fill="#aaaaaa", font=("Segoe UI", 12),
        )

        # Status label
        self._status_label_id = self._canvas.create_text(
            screen_w // 2, screen_h - 30,
            text="Select a terminal to begin calibration",
            fill="#ffcc00", font=("Segoe UI", 14),
        )

        # Gaze dot (starts hidden)
        self._gaze_dot_id = self._canvas.create_oval(
            -100, -100, -100, -100,
            fill="#00ff88", outline="white", width=2,
        )

        # Bindings
        self._canvas.bind("<Button-1>", self._on_click)
        self._root.bind("<s>", self._on_start)
        self._root.bind("<S>", self._on_start)
        self._root.bind("<e>", self._on_end)
        self._root.bind("<E>", self._on_end)
        self._root.bind("<Escape>", self._on_escape)

        # Start periodic updates
        self._root.after(self.POLL_INTERVAL_MS, self._poll_window_positions)
        self._root.after(self.GAZE_INTERVAL_MS, self._update_gaze_dot)

    def _on_click(self, event) -> None:
        x, y = event.x, event.y
        for tr in self._terminal_rects:
            if tr.contains(x, y):
                self._state.select(tr.hwnd)
                self._update_rect_styles()
                self._set_status(f"Selected: {tr.label} — Press S to start recording")
                return
        # Clicked outside all rects
        self._state.selected_hwnd = None
        self._update_rect_styles()
        self._set_status("Select a terminal to begin calibration")

    def _on_start(self, event) -> None:
        if self._state.selected_hwnd is None:
            self._set_status("Select a terminal first!")
            return
        self._state.start_recording()
        label = self._get_label_for_hwnd(self._state.selected_hwnd)
        self._set_status(f"Recording {label}... look around the terminal area. Press E to stop.")
        self._update_rect_styles()

    def _on_end(self, event) -> None:
        if not self._state.recording:
            self._set_status("Not currently recording. Select a terminal and press S first.")
            return

        hwnd = self._state.selected_hwnd
        samples = self._state.stop_recording()
        label = self._get_label_for_hwnd(hwnd)

        if len(samples) < 5:
            self._set_status(f"Only {len(samples)} samples for {label} — not enough. Try again.")
            self._state.calibrated_hwnds.discard(hwnd)
        else:
            xs = [s[0] for s in samples]
            ys = [s[1] for s in samples]
            median_x = float(np.median(xs))
            median_y = float(np.median(ys))
            self._calibration_results[hwnd] = (median_x, median_y)
            self._set_status(
                f"{label} calibrated ({len(samples)} samples). "
                f"Select another terminal or press ESC to finish."
            )

        self._update_rect_styles()

    def _on_escape(self, event) -> None:
        if self._state.recording:
            self._state.stop_recording()
        self._running = False
        self._root.destroy()

    def _poll_window_positions(self) -> None:
        """Update terminal rectangle positions in real-time."""
        if not self._running:
            return

        # Check for new terminals
        current_hwnds = {tr.hwnd for tr in self._terminal_rects}
        discovered = discover_terminals()
        discovered_hwnds = {t.hwnd for t in discovered}

        # Add new terminals
        for t in discovered:
            if t.hwnd not in current_hwnds:
                idx = len(self._terminal_rects) + 1
                tr = TerminalRect(
                    hwnd=t.hwnd, label=f"Terminal {idx}",
                    left=t.rect[0], top=t.rect[1], right=t.rect[2], bottom=t.rect[3],
                )
                self._terminal_rects.append(tr)
                rid = self._canvas.create_rectangle(
                    tr.left, tr.top, tr.right, tr.bottom,
                    outline="white", width=3, fill="",
                )
                self._rect_ids[tr.hwnd] = rid
                cx = (tr.left + tr.right) // 2
                cy = (tr.top + tr.bottom) // 2
                lid = self._canvas.create_text(
                    cx, cy, text=tr.label, fill="white",
                    font=("Segoe UI", 16, "bold"),
                )
                self._label_ids[tr.hwnd] = lid

        # Remove closed terminals
        for tr in list(self._terminal_rects):
            if tr.hwnd not in discovered_hwnds:
                self._terminal_rects.remove(tr)
                if tr.hwnd in self._rect_ids:
                    self._canvas.delete(self._rect_ids.pop(tr.hwnd))
                if tr.hwnd in self._label_ids:
                    self._canvas.delete(self._label_ids.pop(tr.hwnd))
                if tr.hwnd in self._check_ids:
                    self._canvas.delete(self._check_ids.pop(tr.hwnd))

        # Update positions of existing terminals
        for tr in self._terminal_rects:
            rect = get_window_rect(tr.hwnd)
            if rect:
                tr.left, tr.top, tr.right, tr.bottom = rect
                if tr.hwnd in self._rect_ids:
                    self._canvas.coords(
                        self._rect_ids[tr.hwnd],
                        tr.left, tr.top, tr.right, tr.bottom,
                    )
                if tr.hwnd in self._label_ids:
                    cx = (tr.left + tr.right) // 2
                    cy = (tr.top + tr.bottom) // 2
                    self._canvas.coords(self._label_ids[tr.hwnd], cx, cy)

        self._root.after(self.POLL_INTERVAL_MS, self._poll_window_positions)

    def _update_gaze_dot(self) -> None:
        """Move the gaze dot to the current gaze position."""
        if not self._running:
            return

        with self._gaze_lock:
            pos = self._gaze_pos

        if pos and self._gaze_dot_id:
            # pos is normalized (0-1), convert to screen coords
            screen_w = self._root.winfo_screenwidth()
            screen_h = self._root.winfo_screenheight()
            # The gaze values from _get_iris_center are nose-relative amplified values.
            # For the live pointer we scale them to approximate screen position.
            # This won't be perfect pre-calibration but gives directional feedback.
            sx = int(pos[0] * screen_w)
            sy = int(pos[1] * screen_h)
            r = self.GAZE_DOT_RADIUS
            self._canvas.coords(self._gaze_dot_id, sx - r, sy - r, sx + r, sy + r)

            # If recording, add this sample
            if self._state.recording:
                self._state.add_sample(pos[0], pos[1])

        self._root.after(self.GAZE_INTERVAL_MS, self._update_gaze_dot)

    def _gaze_loop(self) -> None:
        """Background thread: capture webcam and compute gaze position."""
        import cv2
        import mediapipe as mp_lib

        model_path = ensure_model()
        cap = cv2.VideoCapture(self._webcam_index)
        if not cap.isOpened():
            logger.error("Cannot open webcam %d", self._webcam_index)
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        options = mp_lib.tasks.vision.FaceLandmarkerOptions(
            base_options=mp_lib.tasks.BaseOptions(model_asset_path=model_path),
            running_mode=mp_lib.tasks.vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.3,
            min_tracking_confidence=0.3,
        )
        landmarker = mp_lib.tasks.vision.FaceLandmarker.create_from_options(options)

        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    continue

                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp_lib.Image(image_format=mp_lib.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect(mp_image)

                if result.face_landmarks:
                    gaze = _get_iris_center(result.face_landmarks[0])
                    if gaze:
                        with self._gaze_lock:
                            self._gaze_pos = gaze
                    else:
                        with self._gaze_lock:
                            self._gaze_pos = None
                else:
                    with self._gaze_lock:
                        self._gaze_pos = None

                import time
                time.sleep(0.03)
        finally:
            landmarker.close()
            cap.release()

    def _update_rect_styles(self) -> None:
        """Update rectangle colors based on selection/recording/calibrated state."""
        for tr in self._terminal_rects:
            rid = self._rect_ids.get(tr.hwnd)
            if not rid:
                continue

            if tr.hwnd in self._state.calibrated_hwnds:
                self._canvas.itemconfig(rid, outline="#00ff00", width=4)
                # Add checkmark if not already present
                if tr.hwnd not in self._check_ids:
                    cx = (tr.left + tr.right) // 2
                    cy = tr.top + 30
                    cid = self._canvas.create_text(
                        cx, cy, text="\u2713", fill="#00ff00",
                        font=("Segoe UI", 24, "bold"),
                    )
                    self._check_ids[tr.hwnd] = cid
            elif tr.hwnd == self._state.selected_hwnd:
                if self._state.recording:
                    self._canvas.itemconfig(rid, outline="#ff4444", width=4)
                else:
                    self._canvas.itemconfig(rid, outline="#ffcc00", width=4)
            else:
                self._canvas.itemconfig(rid, outline="white", width=3)

    def _set_status(self, text: str) -> None:
        if self._status_label_id and self._canvas:
            self._canvas.itemconfig(self._status_label_id, text=text)

    def _get_label_for_hwnd(self, hwnd: int | None) -> str:
        if hwnd is None:
            return "Unknown"
        for tr in self._terminal_rects:
            if tr.hwnd == hwnd:
                return tr.label
        return f"HWND={hwnd}"

    def _build_calibration_data(self) -> CalibrationData | None:
        """Convert per-HWND calibration results to quadrant-based CalibrationData."""
        from eyeclaude.pipe_server import _assign_quadrant_by_position

        if not self._calibration_results:
            return None

        data = CalibrationData()
        for hwnd, (mx, my) in self._calibration_results.items():
            quadrant = _assign_quadrant_by_position(hwnd)
            data.points[quadrant] = (mx, my)

        if len(data.points) < 2:
            logger.warning("Only %d quadrants calibrated — need at least 2", len(data.points))
            return None

        return data
```

- [ ] **Step 2: Manually test the overlay renders**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -c "from eyeclaude.calibration_overlay import CalibrationOverlay; CalibrationOverlay().run()"`

Verify:
- Full-screen dark overlay appears
- Terminal windows shown as white rectangles in correct positions
- Live gaze dot moves on screen
- Click a rectangle → highlights yellow
- Press S → starts recording (red outline)
- Press E → stops recording (green outline with checkmark)
- ESC closes overlay

- [ ] **Step 3: Commit**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
git add src/eyeclaude/calibration_overlay.py
git commit -m "feat: add Tkinter calibration overlay with live gaze pointer"
```

---

### Task 4: Statusline Wrapper

**Files:**
- Create: `src/eyeclaude/statusline_wrapper.py`
- Create: `tests/test_statusline_wrapper.py`
- Modify: `pyproject.toml` (add entry point)

- [ ] **Step 1: Write failing tests for statusline wrapper**

```python
# tests/test_statusline_wrapper.py
"""Tests for statusline wrapper logic."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from eyeclaude.statusline_wrapper import build_indicator, STATUS_DIR


class TestBuildIndicator:
    def test_idle_status(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "idle", "active": False}))
        result = build_indicator(status_file)
        assert result == "\U0001f7e2"  # 🟢

    def test_working_status(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "working", "active": False}))
        result = build_indicator(status_file)
        assert result == "\U0001f535"  # 🔵

    def test_finished_status(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "finished", "active": False}))
        result = build_indicator(status_file)
        assert result == "\U0001f7e1"  # 🟡

    def test_error_status(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "error", "active": False}))
        result = build_indicator(status_file)
        assert result == "\U0001f534"  # 🔴

    def test_active_indicator(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "idle", "active": True}))
        result = build_indicator(status_file)
        assert result == "\U0001f7e2\u25c0"  # 🟢◀

    def test_missing_file_returns_empty(self, tmp_path):
        status_file = tmp_path / "nonexistent.json"
        result = build_indicator(status_file)
        assert result == ""

    def test_corrupt_json_returns_empty(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text("not json")
        result = build_indicator(status_file)
        assert result == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest tests/test_statusline_wrapper.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement statusline_wrapper.py**

```python
# src/eyeclaude/statusline_wrapper.py
"""Statusline wrapper — prepends EyeClaude indicator to ccstatusline output."""

import json
import subprocess
import sys
from pathlib import Path

STATUS_DIR = Path.home() / ".eyeclaude" / "status"

STATUS_EMOJI = {
    "idle": "\U0001f7e2",      # 🟢
    "working": "\U0001f535",    # 🔵
    "finished": "\U0001f7e1",   # 🟡
    "error": "\U0001f534",      # 🔴
}

ACTIVE_INDICATOR = "\u25c0"  # ◀


def build_indicator(status_file: Path) -> str:
    """Read a status JSON file and return the indicator string."""
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
        status = data.get("status", "idle")
        active = data.get("active", False)
        emoji = STATUS_EMOJI.get(status, "")
        if not emoji:
            return ""
        if active:
            return emoji + ACTIVE_INDICATOR
        return emoji
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return ""


def _get_terminal_hwnd() -> int:
    """Get the terminal window handle for this process."""
    try:
        import win32console
        hwnd = win32console.GetConsoleWindow()
        if hwnd:
            return hwnd
    except Exception:
        pass
    try:
        import win32gui
        return win32gui.GetForegroundWindow()
    except Exception:
        return 0


def main():
    """Entry point: read stdin, prepend indicator, pipe through ccstatusline."""
    stdin_data = ""
    try:
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.read()
    except Exception:
        pass

    # Get indicator for this terminal
    hwnd = _get_terminal_hwnd()
    indicator = ""
    if hwnd:
        status_file = STATUS_DIR / f"{hwnd}.json"
        indicator = build_indicator(status_file)

    # Run ccstatusline with the original stdin
    try:
        result = subprocess.run(
            ["npx", "-y", "ccstatusline@latest"],
            input=stdin_data, capture_output=True, text=True, timeout=10,
        )
        ccoutput = result.stdout.strip()
    except Exception:
        ccoutput = ""

    # Combine: indicator + space + ccstatusline output
    if indicator and ccoutput:
        print(f"{indicator} {ccoutput}")
    elif indicator:
        print(indicator)
    elif ccoutput:
        print(ccoutput)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest tests/test_statusline_wrapper.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Add entry point to pyproject.toml**

In `pyproject.toml`, change the `[project.scripts]` section to:

```toml
[project.scripts]
eyeclaude = "eyeclaude.cli:main"
eyeclaude-hooks = "eyeclaude.hooks:main"
eyeclaude-statusline = "eyeclaude.statusline_wrapper:main"
```

- [ ] **Step 6: Commit**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
git add src/eyeclaude/statusline_wrapper.py tests/test_statusline_wrapper.py pyproject.toml
git commit -m "feat: add statusline wrapper for Claude Code status indicator"
```

---

### Task 5: Status File Writer in Pipe Server

**Files:**
- Modify: `src/eyeclaude/pipe_server.py`
- Modify: `tests/test_pipe_server.py`

- [ ] **Step 1: Write failing test for status file writing**

Add to `tests/test_pipe_server.py`:

```python
class TestStatusFileWriter:
    def test_writes_status_file_on_status_message(self, tmp_path):
        from eyeclaude.pipe_server import PipeServer, PipeMessage
        from eyeclaude.shared_state import SharedState, Quadrant

        state = SharedState()
        state.register_terminal(pid=1001, window_handle=1001, quadrant=Quadrant.TOP_LEFT)

        server = PipeServer(state, status_dir=tmp_path)
        msg = PipeMessage(type="status", window_handle=1001, state="working")
        server.handle_message(msg)

        status_file = tmp_path / "1001.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert data["status"] == "working"

    def test_writes_active_flag(self, tmp_path):
        from eyeclaude.pipe_server import PipeServer, PipeMessage
        from eyeclaude.shared_state import SharedState, Quadrant

        state = SharedState()
        state.register_terminal(pid=1001, window_handle=1001, quadrant=Quadrant.TOP_LEFT)
        state.active_quadrant = Quadrant.TOP_LEFT

        server = PipeServer(state, status_dir=tmp_path)
        msg = PipeMessage(type="status", window_handle=1001, state="idle")
        server.handle_message(msg)

        data = json.loads((tmp_path / "1001.json").read_text())
        assert data["active"] is True

    def test_inactive_terminal(self, tmp_path):
        from eyeclaude.pipe_server import PipeServer, PipeMessage
        from eyeclaude.shared_state import SharedState, Quadrant

        state = SharedState()
        state.register_terminal(pid=1001, window_handle=1001, quadrant=Quadrant.TOP_LEFT)
        state.active_quadrant = Quadrant.BOTTOM_RIGHT  # Different quadrant

        server = PipeServer(state, status_dir=tmp_path)
        msg = PipeMessage(type="status", window_handle=1001, state="idle")
        server.handle_message(msg)

        data = json.loads((tmp_path / "1001.json").read_text())
        assert data["active"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest tests/test_pipe_server.py::TestStatusFileWriter -v`
Expected: FAIL — PipeServer doesn't accept `status_dir` parameter

- [ ] **Step 3: Modify PipeServer to write status files**

In `src/eyeclaude/pipe_server.py`, update `PipeServer.__init__` and `handle_message`:

Change the `__init__` signature to:

```python
def __init__(self, state: SharedState, pipe_name: str = PIPE_NAME, status_dir: Path | None = None):
    self._state = state
    self._pipe_name = pipe_name
    self._status_dir = status_dir or (Path.home() / ".eyeclaude" / "status")
    self._running = False
    self._thread: threading.Thread | None = None
```

Add `from pathlib import Path` to the imports at the top.

Add a `_write_status_file` method after `handle_message`:

```python
def _write_status_file(self, window_handle: int, state: str) -> None:
    """Write per-terminal status JSON for the statusline wrapper."""
    self._status_dir.mkdir(parents=True, exist_ok=True)
    terminal = self._state.get_terminal_by_hwnd(window_handle)
    active = False
    if terminal:
        active_quad = self._state.active_quadrant
        active = terminal.quadrant == active_quad
    data = {"status": state, "active": active}
    status_file = self._status_dir / f"{window_handle}.json"
    status_file.write_text(json.dumps(data), encoding="utf-8")
```

In `handle_message`, after updating the status in the `elif msg.type == "status":` block, add a call to write the status file. At the end of the `if msg.window_handle:` branch (after `logger.debug`), add:

```python
self._write_status_file(msg.window_handle, msg.state)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest tests/test_pipe_server.py -v`
Expected: All tests PASS (old + new)

- [ ] **Step 5: Commit**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
git add src/eyeclaude/pipe_server.py tests/test_pipe_server.py
git commit -m "feat: pipe server writes per-terminal status files for statusline"
```

---

### Task 6: Update CLI — New Start Flow

**Files:**
- Modify: `src/eyeclaude/cli.py`

- [ ] **Step 1: Rewrite the `start` command**

Replace the entire `start()` function in `src/eyeclaude/cli.py` with:

```python
@main.command()
def start():
    """Launch EyeClaude with auto-discovery and visual calibration."""
    config = load_config()
    state = SharedState()
    status_monitor = StatusMonitor(state, flash_duration_ms=config.finished_flash_duration_ms)

    # Install hooks globally (idempotent)
    _install_claude_hooks()
    click.echo("Claude Code status hooks verified.")

    # Install statusline wrapper
    _install_statusline()

    # Start pipe server for status messages
    pipe_server = PipeServer(state)
    original_handle = pipe_server.handle_message

    def handle_with_monitor(msg):
        original_handle(msg)
        if msg.type == "status":
            status_map = {"idle": InstanceStatus.IDLE, "working": InstanceStatus.WORKING,
                          "finished": InstanceStatus.FINISHED, "error": InstanceStatus.ERROR}
            new_status = status_map.get(msg.state, InstanceStatus.IDLE)
            if msg.window_handle:
                terminal = state.get_terminal_by_hwnd(msg.window_handle)
                if terminal:
                    status_monitor.on_status_change(pid=terminal.pid, new_status=new_status)
            else:
                status_monitor.on_status_change(pid=msg.pid, new_status=new_status)

    pipe_server.handle_message = handle_with_monitor
    pipe_server.start()
    click.echo(f"Listening on pipe: {PIPE_NAME}")

    # Auto-discover terminals and register them
    from eyeclaude.terminal_discovery import discover_terminals
    discovered = discover_terminals()
    click.echo(f"Found {len(discovered)} terminal window(s).")
    for t in discovered:
        quadrant = _assign_quadrant_by_position(t.hwnd)
        state.register_terminal(pid=t.hwnd, window_handle=t.hwnd, quadrant=quadrant)
        click.echo(f"  Registered: {t.title} ({quadrant.value})")

    # Run visual calibration overlay
    from eyeclaude.calibration_overlay import CalibrationOverlay
    click.echo("Opening calibration overlay...")
    overlay_app = CalibrationOverlay(webcam_index=config.webcam_index)
    calibration = overlay_app.run()

    if calibration is None:
        click.echo("Calibration cancelled or failed. Exiting.")
        pipe_server.stop()
        _restore_statusline()
        return

    save_calibration(calibration)
    click.echo(f"Calibration saved — {len(calibration.points)} quadrants.")

    # Start eye tracking
    eye_tracker = EyeTracker(
        state=state,
        calibration=calibration,
        dwell_time_ms=config.dwell_time_ms,
        webcam_index=config.webcam_index,
    )
    window_manager = WindowManager(state)
    eye_tracker.start()

    click.echo("EyeClaude started. Press Ctrl+C to stop.")

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Main loop
    try:
        while not stop_event.is_set() and not state.shutdown_requested:
            active = state.active_quadrant
            window_manager.update_focus(active)
            status_monitor.tick()
            # Update active flag in status files
            _update_active_status_files(state)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass

    click.echo("\nShutting down...")
    eye_tracker.stop()
    pipe_server.stop()
    _cleanup_status_files()
    _restore_statusline()
    click.echo("EyeClaude stopped.")
```

- [ ] **Step 2: Add the helper functions for statusline management and status file updates**

Add these functions to `cli.py` (before the `start` function):

```python
from eyeclaude.pipe_server import _assign_quadrant_by_position


def _install_statusline():
    """Replace ccstatusline with eyeclaude-statusline wrapper in settings.json."""
    import shutil
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    # Save original statusline config for restoration
    backup_path = Path.home() / ".eyeclaude" / "statusline_backup.json"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if "statusLine" in settings:
        backup_path.write_text(json.dumps(settings["statusLine"]), encoding="utf-8")

    # Find eyeclaude-statusline command
    wrapper_cmd = shutil.which("eyeclaude-statusline")
    if wrapper_cmd:
        cmd = f'"{wrapper_cmd}"'
    else:
        cmd = "eyeclaude-statusline"

    settings["statusLine"] = {
        "type": "command",
        "command": cmd,
        "padding": 0,
    }
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    click.echo("Statusline wrapper installed.")


def _restore_statusline():
    """Restore original statusline config."""
    backup_path = Path.home() / ".eyeclaude" / "statusline_backup.json"
    settings_path = Path.home() / ".claude" / "settings.json"
    if not backup_path.exists() or not settings_path.exists():
        return
    try:
        original = json.loads(backup_path.read_text(encoding="utf-8"))
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["statusLine"] = original
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        backup_path.unlink()
        click.echo("Statusline restored.")
    except Exception:
        pass


def _update_active_status_files(state: SharedState) -> None:
    """Update the active flag in all terminal status files."""
    status_dir = Path.home() / ".eyeclaude" / "status"
    if not status_dir.exists():
        return
    active_quad = state.active_quadrant
    for terminal in state.get_all_terminals():
        status_file = status_dir / f"{terminal.window_handle}.json"
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
                data["active"] = terminal.quadrant == active_quad
                status_file.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass


def _cleanup_status_files() -> None:
    """Remove all status files on shutdown."""
    status_dir = Path.home() / ".eyeclaude" / "status"
    if status_dir.exists():
        for f in status_dir.glob("*.json"):
            f.unlink(missing_ok=True)
```

- [ ] **Step 3: Update the `stop` command to also clean up**

Replace the `stop()` function:

```python
@main.command()
def stop():
    """Send stop signal to a running EyeClaude instance."""
    try:
        _send_pipe_message({"type": "shutdown"})
        click.echo("Stop signal sent.")
    except Exception as e:
        click.echo(f"Could not connect to EyeClaude: {e}")
    _remove_claude_hooks()
    _restore_statusline()
    _cleanup_status_files()
    click.echo("Hooks removed, statusline restored, status files cleaned up.")
```

- [ ] **Step 4: Update the `calibrate` command to use the new overlay**

Replace the `calibrate()` function:

```python
@main.command()
def calibrate():
    """Run or re-run eye tracking calibration using the visual overlay."""
    config = load_config()
    click.echo("Opening calibration overlay...")
    from eyeclaude.calibration_overlay import CalibrationOverlay
    overlay_app = CalibrationOverlay(webcam_index=config.webcam_index)
    result = overlay_app.run()
    if result:
        save_calibration(result)
        click.echo(f"Calibration saved to {DEFAULT_CALIBRATION_PATH}")
    else:
        click.echo("Calibration cancelled.")
```

- [ ] **Step 5: Remove the `register` and `unregister` commands**

Delete the following from `cli.py`:
- The `register()` function (lines 201-226)
- The `_register_one_window()` function (lines 229-241)
- The `_find_all_terminal_windows()` function (lines 244-254)
- The `unregister()` function (lines 257-272)

- [ ] **Step 6: Add missing imports at the top of cli.py**

Ensure these imports are present:

```python
from eyeclaude.shared_state import SharedState, InstanceStatus
from eyeclaude.calibration import save_calibration, DEFAULT_CALIBRATION_PATH
```

(Remove the `from eyeclaude.overlay import Overlay` import since we no longer use it.)

- [ ] **Step 7: Manually test the new start flow**

Run: `eyeclaude start`

Verify:
- Hooks are installed
- Terminals are auto-discovered
- Calibration overlay opens
- After calibration, eye tracking starts
- Ctrl+C stops cleanly

- [ ] **Step 8: Commit**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
git add src/eyeclaude/cli.py
git commit -m "feat: rewrite CLI with auto-discovery, overlay calibration, statusline integration"
```

---

### Task 7: Remove Dead Code & Slash Commands

**Files:**
- Delete: `commands/eyeclaude-register.md`
- Delete: `commands/eyeclaude-unregister.md`
- Delete: `~/.claude/commands/eyeclaude-register.md`
- Delete: `~/.claude/commands/eyeclaude-unregister.md`

- [ ] **Step 1: Remove the slash command files from the repo**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
rm commands/eyeclaude-register.md commands/eyeclaude-unregister.md
```

- [ ] **Step 2: Remove the installed slash commands**

```bash
rm -f ~/.claude/commands/eyeclaude-register.md ~/.claude/commands/eyeclaude-unregister.md
```

- [ ] **Step 3: Commit**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
git add -A commands/
git commit -m "chore: remove deprecated eyeclaude-register/unregister slash commands"
```

---

### Task 8: Update Existing Tests

**Files:**
- Modify: `tests/test_pipe_server.py` (add `import json` if missing)
- Modify: `tests/test_overlay.py` (update for new overlay or remove stale tests)

- [ ] **Step 1: Verify all tests pass**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest -v`

If any tests fail due to removed `register`/`unregister` commands or changed imports, fix them.

- [ ] **Step 2: Remove tests for deleted register command from test_integration.py**

The integration tests for register/unregister via pipe are still valid — the pipe server still accepts those message types for internal use. Only remove tests that reference the deleted CLI commands.

- [ ] **Step 3: Run full test suite again**

Run: `cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
git add tests/
git commit -m "test: update tests for v2 registration redesign"
```

---

### Task 9: Re-install Package & End-to-End Test

**Files:** None (verification only)

- [ ] **Step 1: Reinstall the package**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
pip install -e ".[dev]"
```

- [ ] **Step 2: Verify new entry points exist**

```bash
eyeclaude --help
eyeclaude-statusline --help 2>&1 || python -m eyeclaude.statusline_wrapper
```

Verify:
- `register` and `unregister` no longer appear in `eyeclaude --help`
- `eyeclaude-statusline` is available

- [ ] **Step 3: Full end-to-end test**

1. Open 2+ Windows Terminal windows
2. Run `eyeclaude start`
3. Verify: auto-discovers terminals, overlay opens, can calibrate
4. After calibration, verify eye tracking works
5. In a Claude Code session, submit a prompt — verify statusline shows indicator
6. Ctrl+C to stop — verify clean shutdown

- [ ] **Step 4: Run full test suite one final time**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude && python -m pytest -v
```
Expected: All tests PASS

- [ ] **Step 5: Commit any final fixes**

```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
git add -A
git commit -m "chore: final cleanup for v2 registration redesign"
```
