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


# 2-point calibration: opposite corners fully define the linear mapping
BOUND_STEPS = ["top_left", "bottom_right"]
BOUND_LABELS = {
    "top_left": "Look at the TOP-LEFT corner of your screen, then press SPACE",
    "bottom_right": "Look at the BOTTOM-RIGHT corner of your screen, then press SPACE",
}
BOUND_DONE_MSG = "Calibrated! Move your eyes to test. R to recalibrate, ESC when done."


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
    SMOOTHING_FACTOR = 0.85  # 0 = no smoothing, 1 = no movement

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

        # Open webcam + landmarker if not already provided (reuse for recalibration)
        if self._cap is None or self._landmarker is None:
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
        # Don't close webcam/landmarker — caller can reuse them via get_resources()

        return self._build_calibration_data()

    def get_resources(self) -> tuple:
        """Return (cap, landmarker) for reuse by the eye tracker.
        Caller takes ownership — must close them when done."""
        return self._cap, self._landmarker

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

        # Edge marker — starts at top-left corner
        self._edge_marker_id = self._canvas.create_text(
            40, 40,
            text="\u25e4", fill="#ff4444", font=("Segoe UI", 32, "bold"),
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

        # Instant capture — take the current gaze value right now.
        # No delay, no collection period. This captures the exact moment
        # the user is looking at the corner, before eyes drift to read text.
        step = BOUND_STEPS[self._bound_step_index]
        self._bounds[f"{step}_x"] = gaze[0]
        self._bounds[f"{step}_y"] = gaze[1]
        print(f"  {step}: gaze=({gaze[0]:.4f}, {gaze[1]:.4f})")

        self._bound_step_index += 1

        if self._bound_step_index >= len(BOUND_STEPS):
            self._bounds_done = True
            tlx = self._bounds["top_left_x"]
            tly = self._bounds["top_left_y"]
            brx = self._bounds["bottom_right_x"]
            bry = self._bounds["bottom_right_y"]

            # Ensure top-left has lower gaze values than bottom-right.
            # If not, swap so the linear mapping goes the right direction.
            if tlx > brx:
                self._bounds["top_left_x"], self._bounds["bottom_right_x"] = brx, tlx
                print(f"  X axis swapped: {tlx:.4f} <-> {brx:.4f}")
            if tly > bry:
                self._bounds["top_left_y"], self._bounds["bottom_right_y"] = bry, tly
                print(f"  Y axis swapped: {tly:.4f} <-> {bry:.4f}")

            tlx = self._bounds["top_left_x"]
            tly = self._bounds["top_left_y"]
            brx = self._bounds["bottom_right_x"]
            bry = self._bounds["bottom_right_y"]
            print(f"  Calibrated: TL=({tlx:.4f},{tly:.4f}) BR=({brx:.4f},{bry:.4f})")
            print(f"  X range: {brx-tlx:.4f}  Y range: {bry-tly:.4f}")
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
            "top_left": (40, 40, "\u25e4"),          # ◤
            "bottom_right": (screen_w - 40, screen_h - 40, "\u25e2"),  # ◢
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
        self._smooth_x = None
        self._smooth_y = None
        # Re-create edge marker if it was deleted
        self._edge_marker_id = self._canvas.create_text(
            40, 40,
            text="\u25e4", fill="#ff4444", font=("Segoe UI", 32, "bold"),
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
            # Before calibration, rough direct mapping.
            sx = int(gaze_x * screen_w)
            sy = int(gaze_y * screen_h)
        else:
            # 2-point linear mapping:
            # top_left gaze → screen (0, 0)
            # bottom_right gaze → screen (W, H)
            tlx = self._bounds["top_left_x"]
            tly = self._bounds["top_left_y"]
            brx = self._bounds["bottom_right_x"]
            bry = self._bounds["bottom_right_y"]

            x_range = brx - tlx
            y_range = bry - tly
            if abs(x_range) < 0.001:
                x_range = 0.001
            if abs(y_range) < 0.001:
                y_range = 0.001

            norm_x = (gaze_x - tlx) / x_range
            norm_y = (gaze_y - tly) / y_range

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

        tlx = self._bounds["top_left_x"]
        tly = self._bounds["top_left_y"]
        brx = self._bounds["bottom_right_x"]
        bry = self._bounds["bottom_right_y"]

        x_range = brx - tlx
        y_range = bry - tly
        if abs(x_range) < 0.001 or abs(y_range) < 0.001:
            logger.warning("Calibration bounds too narrow")
            return None

        screen_w = self._screen_w
        screen_h = self._screen_h

        data = CalibrationData()
        for tr in self._terminal_rects:
            quadrant = _assign_quadrant_by_position(tr.hwnd)
            # Map terminal center (screen coords) back to gaze space
            cx = (tr.left + tr.right) / 2
            cy = (tr.top + tr.bottom) / 2
            norm_x = cx / screen_w
            norm_y = cy / screen_h
            gaze_x = tlx + norm_x * x_range
            gaze_y = tly + norm_y * y_range
            data.points[quadrant] = (gaze_x, gaze_y)

        if len(data.points) < 2:
            logger.warning("Only %d quadrants — need at least 2", len(data.points))
            return None

        return data
