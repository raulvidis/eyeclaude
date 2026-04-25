"""MediaPipe gaze tracking and gaze-to-quadrant mapping."""

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import urllib.request

import cv2
import mediapipe as mp
import numpy as np

from eyeclaude.shared_state import Quadrant, SharedState

logger = logging.getLogger(__name__)

# MediaPipe iris landmark indices
LEFT_IRIS_CENTER = 468
RIGHT_IRIS_CENTER = 473

# Eye corner / lid landmarks for relative gaze calculation (camera's perspective)
LEFT_EYE_OUTER = 33
LEFT_EYE_INNER = 133
LEFT_EYE_TOP = 159
LEFT_EYE_BOTTOM = 145

RIGHT_EYE_OUTER = 362
RIGHT_EYE_INNER = 263
RIGHT_EYE_TOP = 386
RIGHT_EYE_BOTTOM = 374

# How much the iris-relative-to-eye-center signal contributes vs head pose.
# Head pose alone = stable but requires moving your head; iris-only = sensitive
# but jittery. The mix below gives smooth tracking that responds to both.
IRIS_GAZE_WEIGHT = 0.4

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
MODEL_DIR = Path.home() / ".eyeclaude"
MODEL_PATH = MODEL_DIR / "face_landmarker.task"


def ensure_model() -> str:
    """Download the FaceLandmarker model if not present. Returns path."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not MODEL_PATH.exists():
        logger.info("Downloading FaceLandmarker model...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        logger.info("Model saved to %s", MODEL_PATH)
    return str(MODEL_PATH)


@dataclass
class CalibrationData:
    """Calibrated mapping from raw gaze coordinates to normalized screen [0,1]^2.

    The affine matrix (2x3) maps `[gx, gy, 1]` → `[screen_x_norm, screen_y_norm]`.
    `points` is a diagnostic record of the captured gaze samples per calibration step.
    """
    affine: np.ndarray | None = None
    points: dict[str, tuple[float, float]] = field(default_factory=dict)

    def is_valid(self) -> bool:
        return self.affine is not None

    def gaze_to_screen_norm(self, gx: float, gy: float) -> tuple[float, float]:
        """Map raw gaze to normalized screen coords [0,1]^2 (clamped)."""
        if self.affine is None:
            return (max(0.0, min(1.0, gx)), max(0.0, min(1.0, gy)))
        v = self.affine @ np.array([gx, gy, 1.0])
        return (max(0.0, min(1.0, float(v[0]))), max(0.0, min(1.0, float(v[1]))))


def fit_affine(
    samples: list[tuple[float, float]],
    targets: list[tuple[float, float]],
) -> np.ndarray:
    """Least-squares fit of a 2x3 affine matrix mapping samples → targets.

    Both inputs are lists of (x, y) tuples of equal length (>= 3 for a unique fit).
    Returns A such that `targets[i] ≈ A @ [samples[i].x, samples[i].y, 1]`.
    """
    if len(samples) != len(targets):
        raise ValueError("samples and targets must have equal length")
    if len(samples) < 3:
        raise ValueError("need at least 3 sample/target pairs")

    M = np.array([[sx, sy, 1.0] for sx, sy in samples], dtype=np.float64)
    T = np.array(targets, dtype=np.float64)
    A_T, *_ = np.linalg.lstsq(M, T, rcond=None)
    return A_T.T  # shape (2, 3)


def map_gaze_to_quadrant(
    gaze: tuple[float, float], calibration: CalibrationData
) -> Quadrant:
    """Map a raw gaze sample to a screen quadrant via the calibrated affine."""
    sx, sy = calibration.gaze_to_screen_norm(gaze[0], gaze[1])
    if sx < 0.5:
        return Quadrant.TOP_LEFT if sy < 0.5 else Quadrant.BOTTOM_LEFT
    return Quadrant.TOP_RIGHT if sy < 0.5 else Quadrant.BOTTOM_RIGHT


class DwellTracker:
    """Tracks gaze dwell time to avoid accidental focus switches."""

    def __init__(self, dwell_time_ms: int = 400):
        self._dwell_time_ms = dwell_time_ms
        self._current_quadrant: Quadrant | None = None
        self._dwell_start_ms: float = 0
        self._last_activated: Quadrant | None = None

    def update(
        self, quadrant: Quadrant | None, timestamp_ms: float
    ) -> Quadrant | None:
        """Update with current gaze quadrant. Returns quadrant if dwell threshold met."""
        if quadrant is None:
            self._current_quadrant = None
            return None

        if quadrant != self._current_quadrant:
            self._current_quadrant = quadrant
            self._dwell_start_ms = timestamp_ms
            return None

        elapsed = timestamp_ms - self._dwell_start_ms
        if elapsed >= self._dwell_time_ms and quadrant != self._last_activated:
            self._last_activated = quadrant
            return quadrant

        return None


class OneEuroFilter:
    """Adaptive low-pass filter for noisy signals (Casiez et al., 2012).

    Low cutoff when the signal is steady (smooth), high cutoff when it moves
    (low lag). Much better feel than a fixed EMA for gaze data.
    """

    def __init__(
        self,
        freq: float = 30.0,
        mincutoff: float = 1.0,
        beta: float = 0.5,
        dcutoff: float = 1.0,
    ):
        self._freq = freq
        self._mincutoff = mincutoff
        self._beta = beta
        self._dcutoff = dcutoff
        self._x_prev: float | None = None
        self._dx_prev: float = 0.0
        self._t_prev: float | None = None

    @staticmethod
    def _alpha(cutoff: float, freq: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        te = 1.0 / max(freq, 1e-6)
        return 1.0 / (1.0 + tau / te)

    def filter(self, x: float, t: float | None = None) -> float:
        if self._x_prev is None:
            self._x_prev = x
            self._t_prev = t
            return x

        if t is not None and self._t_prev is not None:
            dt = t - self._t_prev
            if dt > 1e-6:
                self._freq = 1.0 / dt
        self._t_prev = t

        dx = (x - self._x_prev) * self._freq
        a_d = self._alpha(self._dcutoff, self._freq)
        dx_hat = a_d * dx + (1.0 - a_d) * self._dx_prev

        cutoff = self._mincutoff + self._beta * abs(dx_hat)
        a = self._alpha(cutoff, self._freq)
        x_hat = a * x + (1.0 - a) * self._x_prev

        self._x_prev = x_hat
        self._dx_prev = dx_hat
        return x_hat

    def reset(self) -> None:
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None


def _get_gaze(landmarks) -> tuple[float, float] | None:
    """Combined head-pose + iris-relative gaze signal.

    Head pose (nose tip in normalized image coords) provides a stable, large-range
    base signal. The iris position relative to the eye center, normalized by eye
    dimensions, adds eye-only sensitivity so users don't have to physically turn
    their head between quadrants. Both signals are monotonic in the same direction
    after the horizontal frame flip the tracker applies, so they reinforce.
    """
    try:
        nose = landmarks[1]

        l_iris = landmarks[LEFT_IRIS_CENTER]
        l_outer = landmarks[LEFT_EYE_OUTER]
        l_inner = landmarks[LEFT_EYE_INNER]
        l_top = landmarks[LEFT_EYE_TOP]
        l_bot = landmarks[LEFT_EYE_BOTTOM]

        r_iris = landmarks[RIGHT_IRIS_CENTER]
        r_outer = landmarks[RIGHT_EYE_OUTER]
        r_inner = landmarks[RIGHT_EYE_INNER]
        r_top = landmarks[RIGHT_EYE_TOP]
        r_bot = landmarks[RIGHT_EYE_BOTTOM]

        l_cx = (l_outer.x + l_inner.x) / 2.0
        l_cy = (l_top.y + l_bot.y) / 2.0
        l_w = abs(l_inner.x - l_outer.x) or 1e-3
        l_h = abs(l_bot.y - l_top.y) or 1e-3

        r_cx = (r_outer.x + r_inner.x) / 2.0
        r_cy = (r_top.y + r_bot.y) / 2.0
        r_w = abs(r_inner.x - r_outer.x) or 1e-3
        r_h = abs(r_bot.y - r_top.y) or 1e-3

        eye_dx = ((l_iris.x - l_cx) / l_w + (r_iris.x - r_cx) / r_w) / 2.0
        eye_dy = ((l_iris.y - l_cy) / l_h + (r_iris.y - r_cy) / r_h) / 2.0

        gaze_x = nose.x + IRIS_GAZE_WEIGHT * eye_dx
        gaze_y = nose.y + IRIS_GAZE_WEIGHT * eye_dy
        return (gaze_x, gaze_y)
    except (IndexError, AttributeError):
        return None


class EyeTracker:
    """Captures webcam feed, computes gaze, and updates active quadrant on dwell."""

    def __init__(
        self,
        state: SharedState,
        calibration: CalibrationData,
        dwell_time_ms: int = 400,
        webcam_index: int = 0,
        cap=None,
        landmarker=None,
    ):
        self._state = state
        self._calibration = calibration
        self._dwell = DwellTracker(dwell_time_ms=dwell_time_ms)
        self._webcam_index = webcam_index
        self._running = False
        self._thread: threading.Thread | None = None
        self._cap = cap
        self._landmarker = landmarker
        self._fx = OneEuroFilter(mincutoff=1.0, beta=0.7)
        self._fy = OneEuroFilter(mincutoff=1.0, beta=0.7)

    def start(self) -> None:
        """Start tracking. Uses pre-opened webcam/landmarker if provided, otherwise opens new ones."""
        if self._cap is not None and not self._cap.isOpened():
            logger.warning("Pre-provided webcam is closed; reopening")
            self._cap = None
        if self._cap is None:
            self._cap = cv2.VideoCapture(self._webcam_index)
            if not self._cap.isOpened():
                logger.error("Cannot open webcam %d", self._webcam_index)
                self._cap.release()
                self._cap = None
                return
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        if self._landmarker is None:
            model_path = ensure_model()
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
                running_mode=mp.tasks.vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

        if not self._calibration.is_valid():
            logger.warning("EyeTracker started without a valid affine calibration")

        self._running = True
        self._thread = threading.Thread(target=self._track_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._landmarker:
            self._landmarker.close()
        if self._cap:
            self._cap.release()

    def _track_loop(self) -> None:
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
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect(mp_image)

                gaze = None
                if result.face_landmarks:
                    gaze = _get_gaze(result.face_landmarks[0])

                t = time.monotonic()
                timestamp_ms = t * 1000
                quadrant = None
                if gaze and self._calibration.is_valid():
                    fx = self._fx.filter(gaze[0], t)
                    fy = self._fy.filter(gaze[1], t)
                    quadrant = map_gaze_to_quadrant((fx, fy), self._calibration)
                elif gaze is None:
                    self._fx.reset()
                    self._fy.reset()

                activated = self._dwell.update(quadrant, timestamp_ms)
                if activated:
                    self._state.active_quadrant = activated
        except Exception as e:
            logger.error("Eye tracker error: %s", e)
