# src/eyeclaude/calibration_overlay.py
"""Full-screen Tkinter calibration overlay with live gaze pointer."""

import collections
import logging
import threading
import time
import tkinter as tk
from dataclasses import dataclass

import numpy as np

from eyeclaude.terminal_discovery import discover_terminals, get_window_rect
from eyeclaude.eye_tracker import (
    CalibrationData, OneEuroFilter, _get_gaze, ensure_model, fit_affine,
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
    """Backwards-compatible state container kept for tests; not used by the overlay."""

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


# 5-point calibration: 4 corners + center, fit an affine via least-squares
CALIB_STEPS = ["top_left", "top_right", "bottom_right", "bottom_left", "center"]
CALIB_TARGETS_NORM: dict[str, tuple[float, float]] = {
    "top_left": (0.0, 0.0),
    "top_right": (1.0, 0.0),
    "bottom_right": (1.0, 1.0),
    "bottom_left": (0.0, 1.0),
    "center": (0.5, 0.5),
}
CALIB_LABELS = {
    "top_left": "Look at the TOP-LEFT corner of your screen, then press SPACE",
    "top_right": "Look at the TOP-RIGHT corner of your screen, then press SPACE",
    "bottom_right": "Look at the BOTTOM-RIGHT corner of your screen, then press SPACE",
    "bottom_left": "Look at the BOTTOM-LEFT corner of your screen, then press SPACE",
    "center": "Look at the CENTER of your screen, then press SPACE",
}
CALIB_DONE_MSG = "Calibrated! Move your eyes to test. R to recalibrate, ESC when done."

# Sample averaging window for each SPACE press
CAPTURE_WINDOW_SEC = 0.4
CAPTURE_MIN_SAMPLES = 8
CAPTURE_MAX_STD = 0.06  # reject if per-axis std-dev exceeds this


class CalibrationOverlay:
    """Full-screen Tkinter overlay that walks the user through 5-point gaze
    calibration and fits an affine transform from gaze to screen coordinates."""

    GAZE_DOT_RADIUS = 12
    BG_OPACITY = 0.7
    POLL_INTERVAL_MS = 100
    GAZE_INTERVAL_MS = 33

    def __init__(self, webcam_index: int = 0):
        self._webcam_index = webcam_index
        self._terminal_rects: list[TerminalRect] = []
        self._running = False
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._gaze_dot_id: int | None = None
        self._status_label_id: int | None = None
        self._edge_marker_id: int | None = None
        self._rect_ids: dict[int, int] = {}
        self._label_ids: dict[int, int] = {}

        # Gaze tracking
        self._gaze_thread: threading.Thread | None = None
        self._gaze_lock = threading.Lock()
        self._raw_gaze: tuple[float, float] | None = None
        self._gaze_history: collections.deque[tuple[float, float | None, float | None]] = collections.deque(maxlen=64)
        self._camera_error: str | None = None
        self._cap = None
        self._landmarker = None

        # 5-point calibration
        self._step_index: int = 0
        self._captures: dict[str, tuple[float, float]] = {}
        self._calibration_done: bool = False
        self._affine: np.ndarray | None = None

        # One-euro smoothing for the live preview dot
        self._fx = OneEuroFilter(mincutoff=1.0, beta=0.7)
        self._fy = OneEuroFilter(mincutoff=1.0, beta=0.7)

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

        # Open webcam + landmarker if not already provided (reuse for recalibration).
        # Only open the ones that are missing — don't overwrite caller-provided resources.
        if self._cap is None:
            self._cap = cv2.VideoCapture(self._webcam_index)
            if not self._cap.isOpened():
                logger.error("Cannot open webcam %d", self._webcam_index)
                self._cap.release()
                self._cap = None
                return None
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        if self._landmarker is None:
            try:
                model_path = ensure_model()
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
                self._cap = None
                return None

        ret, _ = self._cap.read()
        if not ret:
            logger.error("Webcam opened but cannot read frames")
            self._landmarker.close()
            self._cap.release()
            self._landmarker = None
            self._cap = None
            return None

        self._gaze_thread = threading.Thread(target=self._gaze_loop, daemon=True)
        self._gaze_thread.start()

        self._build_gui()
        self._root.mainloop()

        self._running = False
        if self._gaze_thread:
            self._gaze_thread.join(timeout=1.0)
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

        self._status_label_id = self._canvas.create_text(
            screen_w // 2, screen_h - 40,
            text=CALIB_LABELS[CALIB_STEPS[0]],
            fill="#ffcc00", font=("Segoe UI", 16, "bold"),
        )

        self._gaze_dot_id = self._canvas.create_oval(
            -100, -100, -100, -100,
            fill="#00ff88", outline="white", width=2,
        )

        self._edge_marker_id = self._canvas.create_text(
            40, 40,
            text="◤", fill="#ff4444", font=("Segoe UI", 32, "bold"),
        )
        self._update_edge_marker()

        self._root.focus_force()
        self._root.bind("<space>", self._on_space)
        self._root.bind("<r>", self._on_recalibrate)
        self._root.bind("<R>", self._on_recalibrate)
        self._root.bind("<Escape>", self._on_escape)

        self._root.after(self.POLL_INTERVAL_MS, self._poll_window_positions)
        self._root.after(self.GAZE_INTERVAL_MS, self._update_gaze_dot)

    def _on_space(self, event) -> None:
        if self._calibration_done:
            return

        # Pull samples from the last CAPTURE_WINDOW_SEC and median-average them.
        cutoff = time.monotonic() - CAPTURE_WINDOW_SEC
        with self._gaze_lock:
            window = [(gx, gy) for ts, gx, gy in self._gaze_history
                      if ts >= cutoff and gx is not None and gy is not None]

        if len(window) < CAPTURE_MIN_SAMPLES:
            self._set_status(
                f"Not enough samples ({len(window)}/{CAPTURE_MIN_SAMPLES}). "
                "Hold still and look at the marker, then press SPACE."
            )
            return

        xs = np.array([w[0] for w in window])
        ys = np.array([w[1] for w in window])
        if xs.std() > CAPTURE_MAX_STD or ys.std() > CAPTURE_MAX_STD:
            self._set_status(
                f"Gaze too noisy (std {xs.std():.3f}, {ys.std():.3f}). Hold still and retry."
            )
            return

        gx = float(np.median(xs))
        gy = float(np.median(ys))

        step = CALIB_STEPS[self._step_index]
        self._captures[step] = (gx, gy)
        logger.info("Captured %s: gaze=(%.4f, %.4f) from %d samples", step, gx, gy, len(window))

        self._step_index += 1
        if self._step_index >= len(CALIB_STEPS):
            self._finish_calibration()
        else:
            self._set_status(CALIB_LABELS[CALIB_STEPS[self._step_index]])
            self._update_edge_marker()

    def _finish_calibration(self) -> None:
        samples = [self._captures[s] for s in CALIB_STEPS]
        targets = [CALIB_TARGETS_NORM[s] for s in CALIB_STEPS]
        try:
            self._affine = fit_affine(samples, targets)
        except Exception as e:
            logger.error("Affine fit failed: %s", e)
            self._set_status(f"Calibration fit failed: {e}. Press R to retry.")
            return

        # Sanity check: residual at the captured points should be reasonable.
        # An affine fit through 5 points can't be perfect when real gaze data
        # has noise, so a single value is unlikely to be tiny — we mainly want
        # to catch cases where one axis collapses to noise (mean residual blows up).
        residuals = []
        for (sx, sy), (tx, ty) in zip(samples, targets):
            pred = self._affine @ np.array([sx, sy, 1.0])
            residuals.append(np.hypot(pred[0] - tx, pred[1] - ty))
        max_res = max(residuals)
        mean_res = float(np.mean(residuals))
        x_spread = max(s[0] for s in samples) - min(s[0] for s in samples)
        y_spread = max(s[1] for s in samples) - min(s[1] for s in samples)
        logger.info(
            "Calibration: x_spread=%.3f y_spread=%.3f residuals max=%.3f mean=%.3f",
            x_spread, y_spread, max_res, mean_res,
        )

        # Each axis needs measurable spread. If the user kept their eyes fixed
        # on one axis, no affine can recover the mapping.
        if x_spread < 0.03 or y_spread < 0.03:
            self._set_status(
                f"Gaze barely moved on one axis (X={x_spread:.3f}, Y={y_spread:.3f}). "
                "Move only your eyes between markers, not your head. Press R to retry."
            )
            return

        if mean_res > 0.30:
            self._set_status(
                f"Calibration too inconsistent (mean residual {mean_res:.2f}). "
                "Hold your head still, look only at each marker. Press R to retry."
            )
            return

        self._calibration_done = True
        if self._edge_marker_id is not None:
            self._canvas.delete(self._edge_marker_id)
            self._edge_marker_id = None
        self._set_status(CALIB_DONE_MSG)

    def _update_edge_marker(self) -> None:
        if self._calibration_done or self._edge_marker_id is None:
            return

        screen_w = self._screen_w
        screen_h = self._screen_h
        step = CALIB_STEPS[self._step_index]
        positions = {
            "top_left": (40, 40, "◤"),                    # ◤
            "top_right": (screen_w - 40, 40, "◥"),         # ◥
            "bottom_right": (screen_w - 40, screen_h - 40, "◢"),  # ◢
            "bottom_left": (40, screen_h - 40, "◣"),       # ◣
            "center": (screen_w // 2, screen_h // 2, "●"), # ●
        }
        x, y, marker = positions[step]
        self._canvas.coords(self._edge_marker_id, x, y)
        self._canvas.itemconfig(self._edge_marker_id, text=marker)

    def _on_escape(self, event) -> None:
        self._running = False
        self._root.destroy()

    def _on_recalibrate(self, event) -> None:
        """Reset calibration and start over."""
        self._step_index = 0
        self._captures = {}
        self._calibration_done = False
        self._affine = None
        self._fx.reset()
        self._fy.reset()
        if self._edge_marker_id is None:
            self._edge_marker_id = self._canvas.create_text(
                40, 40,
                text="◤", fill="#ff4444", font=("Segoe UI", 32, "bold"),
            )
        self._update_edge_marker()
        self._set_status(CALIB_LABELS[CALIB_STEPS[0]])

    def _set_status(self, text: str) -> None:
        if self._status_label_id and self._canvas:
            self._canvas.itemconfig(self._status_label_id, text=text)

    def _map_gaze_to_screen(self, gaze_x: float, gaze_y: float) -> tuple[int, int]:
        """Map raw gaze to screen pixel coordinates for the live preview dot."""
        screen_w = self._screen_w
        screen_h = self._screen_h

        if self._affine is None:
            sx = int(gaze_x * screen_w)
            sy = int(gaze_y * screen_h)
        else:
            v = self._affine @ np.array([gaze_x, gaze_y, 1.0])
            sx = int(v[0] * screen_w)
            sy = int(v[1] * screen_h)

        return (max(0, min(screen_w, sx)), max(0, min(screen_h, sy)))

    def _update_gaze_dot(self) -> None:
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
            t = time.monotonic()
            fx = self._fx.filter(gaze[0], t)
            fy = self._fy.filter(gaze[1], t)
            sx, sy = self._map_gaze_to_screen(fx, fy)
            r = self.GAZE_DOT_RADIUS
            self._canvas.coords(self._gaze_dot_id, sx - r, sy - r, sx + r, sy + r)
            self._canvas.tag_raise(self._gaze_dot_id)

        self._root.after(self.GAZE_INTERVAL_MS, self._update_gaze_dot)

    def _poll_window_positions(self) -> None:
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

                gaze = None
                if result.face_landmarks:
                    gaze = _get_gaze(result.face_landmarks[0])

                ts = time.monotonic()
                with self._gaze_lock:
                    self._raw_gaze = gaze
                    if gaze is None:
                        self._gaze_history.append((ts, None, None))
                    else:
                        self._gaze_history.append((ts, gaze[0], gaze[1]))

                time.sleep(0.03)
        except Exception as e:
            logger.error("Gaze loop error: %s", e)
            with self._gaze_lock:
                self._camera_error = f"Tracking error: {e}"

    def _build_calibration_data(self) -> CalibrationData | None:
        if not self._calibration_done or self._affine is None:
            return None
        return CalibrationData(
            affine=self._affine,
            points=dict(self._captures),
        )
