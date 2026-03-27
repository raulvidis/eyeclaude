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


# Bounds calibration steps — center first to establish baseline
BOUND_STEPS = ["center", "left", "right", "top", "bottom"]
BOUND_LABELS = {
    "center": "Look at the CENTER of your screen, then press SPACE",
    "left": "Look at the LEFT edge of your screen, then press SPACE",
    "right": "Look at the RIGHT edge of your screen, then press SPACE",
    "top": "Look at the TOP edge of your screen, then press SPACE",
    "bottom": "Look at the BOTTOM edge of your screen, then press SPACE",
}
BOUND_DONE_MSG = "Bounds calibrated! Move your eyes to test. R to recalibrate, ESC when done."


class CalibrationOverlay:
    """Full-screen Tkinter overlay for bounds-based gaze calibration.

    Step 1: User looks at left/right/top/bottom screen edges to set gaze bounds.
    Step 2: Gaze is linearly mapped from those bounds to full screen.
    Terminal rectangles are shown as visual reference throughout.
    """

    GAZE_DOT_RADIUS = 12
    BG_OPACITY = 0.7
    POLL_INTERVAL_MS = 100
    GAZE_INTERVAL_MS = 33
    SMOOTHING_FACTOR = 0.7  # 0 = no smoothing, 1 = no movement

    def __init__(self, webcam_index: int = 0):
        self._webcam_index = webcam_index
        self._terminal_rects: list[TerminalRect] = []
        self._running = False
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._gaze_dot_id: int | None = None
        self._status_label_id: int | None = None
        self._rect_ids: dict[int, int] = {}
        self._label_ids: dict[int, int] = {}

        # Gaze tracking
        self._gaze_thread: threading.Thread | None = None
        self._gaze_lock = threading.Lock()
        self._raw_gaze: tuple[float, float] | None = None  # Raw _get_iris_center output
        self._camera_error: str | None = None
        self._cap = None
        self._landmarker = None

        # Bounds calibration
        self._bound_step_index: int = 0
        self._bounds: dict[str, float] = {}
        self._bounds_done: bool = False
        self._collecting_samples: list[tuple[float, float]] = []
        self._collecting: bool = False
        self._x_inverted: bool = False
        self._y_inverted: bool = False

        # Smoothing
        self._smooth_x: float | None = None
        self._smooth_y: float | None = None

        # Cached screen dimensions (so we don't call winfo after destroy)
        self._screen_w: int = 1920
        self._screen_h: int = 1080

    def run(self) -> CalibrationData | None:
        """Open the overlay, run calibration, return results. Blocks until closed."""
        import cv2
        import mediapipe as mp_lib

        self._running = True

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

        # Open webcam on main thread (Windows DirectShow requirement)
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

        ret, _ = self._cap.read()
        if not ret:
            logger.error("Webcam opened but cannot read frames")
            self._landmarker.close()
            self._cap.release()
            return None

        self._gaze_thread = threading.Thread(target=self._gaze_loop, daemon=True)
        self._gaze_thread.start()

        self._build_gui()
        self._root.mainloop()

        self._running = False
        time.sleep(0.1)
        self._landmarker.close()
        self._cap.release()

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
        self._screen_w = screen_w
        self._screen_h = screen_h

        self._canvas = tk.Canvas(
            self._root, width=screen_w, height=screen_h,
            bg="black", highlightthickness=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Draw terminal rectangles as visual reference
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

        # Status label
        self._status_label_id = self._canvas.create_text(
            screen_w // 2, screen_h - 40,
            text=BOUND_LABELS[BOUND_STEPS[0]],
            fill="#ffcc00", font=("Segoe UI", 16, "bold"),
        )

        # Gaze dot
        self._gaze_dot_id = self._canvas.create_oval(
            -100, -100, -100, -100,
            fill="#00ff88", outline="white", width=2,
        )

        # Edge marker — starts at center
        self._edge_marker_id = self._canvas.create_text(
            screen_w // 2, screen_h // 2,
            text="\u25cf", fill="#ff4444", font=("Segoe UI", 32, "bold"),
        )

        # Key bindings — focus_force ensures keys work in fullscreen overlay
        self._root.focus_force()
        self._root.bind("<space>", self._on_space)
        self._root.bind("<r>", self._on_recalibrate)
        self._root.bind("<R>", self._on_recalibrate)
        self._root.bind("<Escape>", self._on_escape)

        # Periodic updates
        self._root.after(self.POLL_INTERVAL_MS, self._poll_window_positions)
        self._root.after(self.GAZE_INTERVAL_MS, self._update_gaze_dot)

    def _on_space(self, event) -> None:
        if self._bounds_done:
            return

        with self._gaze_lock:
            gaze = self._raw_gaze

        if gaze is None:
            self._set_status("No face detected! Look at the camera.")
            return

        # Start collecting samples for this bound
        if not self._collecting:
            self._collecting = True
            self._collecting_samples = []
            self._set_status("Hold still... recording (1s)")
            # Visual feedback — dot turns red during recording
            if self._gaze_dot_id:
                self._canvas.itemconfig(self._gaze_dot_id, fill="#ff4444")
            self._root.after(1000, self._finalize_bound)
            return

    def _finalize_bound(self) -> None:
        """Called after 1 second of sample collection."""
        self._collecting = False
        # Restore dot color
        if self._gaze_dot_id:
            self._canvas.itemconfig(self._gaze_dot_id, fill="#00ff88")
        step = BOUND_STEPS[self._bound_step_index]

        if len(self._collecting_samples) < 5:
            self._set_status(f"Not enough samples. Try again: {BOUND_LABELS[step]}")
            return

        xs = [s[0] for s in self._collecting_samples]
        ys = [s[1] for s in self._collecting_samples]
        median_x = float(np.median(xs))
        median_y = float(np.median(ys))

        if step == "center":
            self._bounds["center_x"] = median_x
            self._bounds["center_y"] = median_y
        elif step in ("left", "right"):
            self._bounds[step] = median_x
        else:  # top, bottom
            self._bounds[step] = median_y

        self._bound_step_index += 1

        if self._bound_step_index >= len(BOUND_STEPS):
            self._bounds_done = True
            # Both axes are inverted due to flipped webcam + amplified iris math:
            # looking left → higher gaze_x, looking up → higher gaze_y
            self._x_inverted = True
            self._y_inverted = True
            self._set_status(BOUND_DONE_MSG)
            self._update_edge_marker()
        else:
            next_step = BOUND_STEPS[self._bound_step_index]
            self._set_status(BOUND_LABELS[next_step])
            self._update_edge_marker()

    def _update_edge_marker(self) -> None:
        """Move the edge marker arrow to indicate where to look."""
        if self._bounds_done:
            self._canvas.delete(self._edge_marker_id)
            return

        screen_w = self._screen_w
        screen_h = self._screen_h
        step = BOUND_STEPS[self._bound_step_index]

        positions = {
            "center": (screen_w // 2, screen_h // 2, "\u25cf"),  # ●
            "left": (30, screen_h // 2, "\u25c0"),                # ◀
            "right": (screen_w - 30, screen_h // 2, "\u25b6"),    # ▶
            "top": (screen_w // 2, 60, "\u25b2"),                 # ▲
            "bottom": (screen_w // 2, screen_h - 70, "\u25bc"),   # ▼
        }
        x, y, arrow = positions[step]
        self._canvas.coords(self._edge_marker_id, x, y)
        self._canvas.itemconfig(self._edge_marker_id, text=arrow)

    def _on_escape(self, event) -> None:
        self._running = False
        self._root.destroy()

    def _on_recalibrate(self, event) -> None:
        """Reset calibration and start over from center."""
        self._bound_step_index = 0
        self._bounds = {}
        self._bounds_done = False
        self._collecting = False
        self._x_inverted = False
        self._y_inverted = False
        self._smooth_x = None
        self._smooth_y = None
        # Re-create edge marker if it was deleted
        screen_w, screen_h = self._screen_w, self._screen_h
        self._edge_marker_id = self._canvas.create_text(
            screen_w // 2, screen_h // 2,
            text="\u25cf", fill="#ff4444", font=("Segoe UI", 32, "bold"),
        )
        self._set_status(BOUND_LABELS[BOUND_STEPS[0]])

    def _set_status(self, text: str) -> None:
        if self._status_label_id and self._canvas:
            self._canvas.itemconfig(self._status_label_id, text=text)

    def _map_gaze_to_screen(self, gaze_x: float, gaze_y: float) -> tuple[int, int]:
        """Map raw gaze values to screen coordinates using calibrated bounds."""
        screen_w = self._screen_w
        screen_h = self._screen_h

        if not self._bounds_done:
            # Before calibration, rough mapping. Both axes are inverted:
            # flipped webcam + amplified iris offset = looking-left gives higher X,
            # looking-up gives higher Y.
            sx = int((1.0 - gaze_x) * screen_w)
            sy = int((1.0 - gaze_y) * screen_h)
        else:
            # Bounds are recorded as raw gaze values when looking at each edge.
            # The mapping is: left_bound → screen 0, right_bound → screen 1.
            # This works regardless of whether the axis is inverted, because
            # the bounds themselves encode the direction.
            bnd_left = self._bounds["left"]
            bnd_right = self._bounds["right"]
            bnd_top = self._bounds["top"]
            bnd_bottom = self._bounds["bottom"]

            x_range = bnd_right - bnd_left
            y_range = bnd_bottom - bnd_top
            if abs(x_range) < 0.001:
                x_range = 0.001
            if abs(y_range) < 0.001:
                y_range = 0.001

            norm_x = (gaze_x - bnd_left) / x_range
            norm_y = (gaze_y - bnd_top) / y_range

            sx = int(norm_x * screen_w)
            sy = int(norm_y * screen_h)

        return (max(0, min(screen_w, sx)), max(0, min(screen_h, sy)))

    def _update_gaze_dot(self) -> None:
        """Move the gaze dot to the current gaze position."""
        if not self._running:
            return

        with self._gaze_lock:
            gaze = self._raw_gaze
            cam_err = self._camera_error

        if cam_err:
            self._set_status(f"Camera error: {cam_err}")
            self._root.after(self.GAZE_INTERVAL_MS, self._update_gaze_dot)
            return

        if gaze and self._gaze_dot_id:
            sx, sy = self._map_gaze_to_screen(gaze[0], gaze[1])

            # Exponential moving average for smoothing
            alpha = 1.0 - self.SMOOTHING_FACTOR
            if self._smooth_x is None:
                self._smooth_x = float(sx)
                self._smooth_y = float(sy)
            else:
                self._smooth_x = alpha * sx + self.SMOOTHING_FACTOR * self._smooth_x
                self._smooth_y = alpha * sy + self.SMOOTHING_FACTOR * self._smooth_y

            dx = int(self._smooth_x)
            dy = int(self._smooth_y)
            r = self.GAZE_DOT_RADIUS
            self._canvas.coords(self._gaze_dot_id, dx - r, dy - r, dx + r, dy + r)
            self._canvas.tag_raise(self._gaze_dot_id)

            # Collect samples during bound calibration
            if self._collecting:
                self._collecting_samples.append(gaze)

        self._root.after(self.GAZE_INTERVAL_MS, self._update_gaze_dot)

    def _poll_window_positions(self) -> None:
        """Update terminal rectangle positions in real-time."""
        if not self._running:
            return

        current_hwnds = {tr.hwnd for tr in self._terminal_rects}
        discovered = discover_terminals()
        discovered_hwnds = {t.hwnd for t in discovered}

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

        for tr in list(self._terminal_rects):
            if tr.hwnd not in discovered_hwnds:
                self._terminal_rects.remove(tr)
                if tr.hwnd in self._rect_ids:
                    self._canvas.delete(self._rect_ids.pop(tr.hwnd))
                if tr.hwnd in self._label_ids:
                    self._canvas.delete(self._label_ids.pop(tr.hwnd))

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
                    gaze = _get_iris_center(result.face_landmarks[0])
                    with self._gaze_lock:
                        self._raw_gaze = gaze
                else:
                    with self._gaze_lock:
                        self._raw_gaze = None

                time.sleep(0.03)
        except Exception as e:
            logger.error("Gaze loop error: %s", e)
            with self._gaze_lock:
                self._camera_error = f"Tracking error: {e}"

    def _build_calibration_data(self) -> CalibrationData | None:
        """Build CalibrationData from bounds calibration.

        Maps each terminal's screen center to gaze space using the calibrated
        bounds, producing the same quadrant-based CalibrationData the eye
        tracker expects.
        """
        from eyeclaude.pipe_server import _assign_quadrant_by_position

        if not self._bounds_done:
            return None

        bnd_left = self._bounds["left"]
        bnd_right = self._bounds["right"]
        bnd_top = self._bounds["top"]
        bnd_bottom = self._bounds["bottom"]

        x_range = bnd_right - bnd_left
        y_range = bnd_bottom - bnd_top
        if abs(x_range) < 0.001 or abs(y_range) < 0.001:
            logger.warning("Calibration bounds too narrow")
            return None

        # Use cached screen dimensions (root may be destroyed by now)
        screen_w = self._screen_w
        screen_h = self._screen_h

        data = CalibrationData()
        for tr in self._terminal_rects:
            quadrant = _assign_quadrant_by_position(tr.hwnd)
            # Map terminal center (screen coords) to gaze space.
            # Bounds encode direction naturally (left_bound maps to screen 0,
            # right_bound maps to screen 1), so no inversion needed.
            cx = (tr.left + tr.right) / 2
            cy = (tr.top + tr.bottom) / 2
            norm_x = cx / screen_w
            norm_y = cy / screen_h
            gaze_x = bnd_left + norm_x * x_range
            gaze_y = bnd_top + norm_y * y_range
            data.points[quadrant] = (gaze_x, gaze_y)

        if len(data.points) < 2:
            logger.warning("Only %d quadrants — need at least 2", len(data.points))
            return None

        return data
