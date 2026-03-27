# src/eyeclaude/calibration_overlay.py
"""Full-screen Tkinter calibration overlay with live gaze pointer."""

import logging
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field

import numpy as np

from eyeclaude.terminal_discovery import discover_terminals, get_window_rect, DiscoveredTerminal
from eyeclaude.eye_tracker import (
    CalibrationData, _get_iris_center, ensure_model,
    LEFT_IRIS_CENTER, RIGHT_IRIS_CENTER,
)

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
        self._gaze_pos: tuple[float, float] | None = None  # Raw iris position (0-1) for dot
        self._gaze_calibration_pos: tuple[float, float] | None = None  # Amplified pos for calibration
        self._camera_error: str | None = None  # Surfaced to UI
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
        # Webcam + landmarker opened on main thread, read from gaze thread
        self._cap = None
        self._landmarker = None

    def run(self) -> CalibrationData | None:
        """Open the overlay, run calibration, return results. Blocks until closed."""
        import cv2
        import mediapipe as mp_lib

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

        # Open webcam on main thread — Windows DirectShow/MSMF backends
        # can fail to read frames when opened from a non-main thread.
        try:
            model_path = ensure_model()
        except Exception as e:
            logger.error("Model download failed: %s", e)
            return None

        self._cap = cv2.VideoCapture(self._webcam_index)
        if not self._cap.isOpened():
            logger.error("Cannot open webcam %d", self._webcam_index)
            return None

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        try:
            options = mp_lib.tasks.vision.FaceLandmarkerOptions(
                base_options=mp_lib.tasks.BaseOptions(model_asset_path=model_path),
                running_mode=mp_lib.tasks.vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.3,
                min_tracking_confidence=0.3,
            )
            self._landmarker = mp_lib.tasks.vision.FaceLandmarker.create_from_options(options)
        except Exception as e:
            logger.error("MediaPipe init failed: %s", e)
            self._cap.release()
            return None

        # Verify we can actually read a frame
        ret, _ = self._cap.read()
        if not ret:
            logger.error("Webcam opened but cannot read frames")
            self._landmarker.close()
            self._cap.release()
            return None

        # Start gaze tracking thread (webcam already open)
        self._gaze_thread = threading.Thread(target=self._gaze_loop, daemon=True)
        self._gaze_thread.start()

        # Build and run Tkinter
        self._build_gui()
        self._root.mainloop()

        # Cleanup
        self._running = False
        time.sleep(0.1)  # Let gaze thread exit
        self._landmarker.close()
        self._cap.release()

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
            dot_pos = self._gaze_pos  # Raw iris (0-1) for visual dot
            cal_pos = self._gaze_calibration_pos  # Amplified for calibration samples
            cam_err = self._camera_error

        # Show camera errors in the status bar
        if cam_err:
            self._set_status(f"Camera error: {cam_err}")
            self._root.after(self.GAZE_INTERVAL_MS, self._update_gaze_dot)
            return

        if dot_pos and self._gaze_dot_id:
            screen_w = self._root.winfo_screenwidth()
            screen_h = self._root.winfo_screenheight()
            # Raw iris x/y from MediaPipe are in [0,1] image-space.
            # Frame is already flipped (cv2.flip(frame, 1)) so x maps directly.
            sx = int(dot_pos[0] * screen_w)
            sy = int(dot_pos[1] * screen_h)
            sx = max(0, min(screen_w, sx))
            sy = max(0, min(screen_h, sy))
            r = self.GAZE_DOT_RADIUS
            self._canvas.coords(self._gaze_dot_id, sx - r, sy - r, sx + r, sy + r)
            self._canvas.tag_raise(self._gaze_dot_id)

            # Record amplified gaze values for calibration (what the eye tracker uses)
            if self._state.recording and cal_pos:
                self._state.add_sample(cal_pos[0], cal_pos[1])

        self._root.after(self.GAZE_INTERVAL_MS, self._update_gaze_dot)

    def _gaze_loop(self) -> None:
        """Background thread: read frames from pre-opened webcam and compute gaze."""
        import cv2
        import mediapipe as mp_lib

        cap = self._cap
        landmarker = self._landmarker

        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue

                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp_lib.Image(image_format=mp_lib.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect(mp_image)

                if result.face_landmarks:
                    landmarks = result.face_landmarks[0]
                    # Raw iris position for the visual dot (0-1 image space)
                    try:
                        l_iris = landmarks[LEFT_IRIS_CENTER]
                        r_iris = landmarks[RIGHT_IRIS_CENTER]
                        raw_x = (l_iris.x + r_iris.x) / 2
                        raw_y = (l_iris.y + r_iris.y) / 2
                        raw_pos = (raw_x, raw_y)
                    except (IndexError, AttributeError):
                        raw_pos = None

                    # Amplified gaze for calibration recording
                    cal_pos = _get_iris_center(landmarks)

                    with self._gaze_lock:
                        self._gaze_pos = raw_pos
                        self._gaze_calibration_pos = cal_pos
                else:
                    with self._gaze_lock:
                        self._gaze_pos = None
                        self._gaze_calibration_pos = None

                time.sleep(0.03)
        except Exception as e:
            logger.error("Gaze loop error: %s", e)
            with self._gaze_lock:
                self._camera_error = f"Tracking error: {e}"

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
