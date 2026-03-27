"""MediaPipe iris tracking and gaze-to-quadrant mapping."""

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import urllib.request

import cv2
import mediapipe as mp

from eyeclaude.shared_state import Quadrant, SharedState

logger = logging.getLogger(__name__)

# MediaPipe iris landmark indices
LEFT_IRIS_CENTER = 468
RIGHT_IRIS_CENTER = 473

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
    """Maps each quadrant to its calibrated iris position (normalized x, y)."""
    points: dict[Quadrant, tuple[float, float]] = field(default_factory=dict)


def map_gaze_to_quadrant(
    gaze: tuple[float, float], calibration: CalibrationData
) -> Quadrant:
    """Find the nearest calibrated quadrant to the current gaze position."""
    gx, gy = gaze
    best_quadrant = Quadrant.TOP_LEFT
    best_dist = float("inf")

    for quadrant, (cx, cy) in calibration.points.items():
        dist = math.hypot(gx - cx, gy - cy)
        if dist < best_dist:
            best_dist = dist
            best_quadrant = quadrant

    return best_quadrant


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


def _get_iris_center(landmarks) -> tuple[float, float] | None:
    """Extract averaged iris center from both eyes."""
    try:
        left = landmarks[LEFT_IRIS_CENTER]
        right = landmarks[RIGHT_IRIS_CENTER]
        return ((left.x + right.x) / 2, (left.y + right.y) / 2)
    except (IndexError, AttributeError):
        return None


class EyeTracker:
    """Captures webcam feed and tracks iris position using MediaPipe."""

    def __init__(
        self,
        state: SharedState,
        calibration: CalibrationData,
        dwell_time_ms: int = 400,
        webcam_index: int = 0,
    ):
        self._state = state
        self._calibration = calibration
        self._dwell = DwellTracker(dwell_time_ms=dwell_time_ms)
        self._webcam_index = webcam_index
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._track_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _track_loop(self) -> None:
        cap = cv2.VideoCapture(self._webcam_index)
        if not cap.isOpened():
            logger.error("Cannot open webcam %d", self._webcam_index)
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        model_path = ensure_model()
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    continue

                frame = cv2.flip(frame, 1)  # Mirror for natural feel
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect(mp_image)

                gaze = None
                if result.face_landmarks:
                    landmarks = result.face_landmarks[0]
                    gaze = _get_iris_center(landmarks)

                timestamp_ms = time.monotonic() * 1000
                quadrant = None
                if gaze and self._calibration.points:
                    quadrant = map_gaze_to_quadrant(gaze, self._calibration)

                activated = self._dwell.update(quadrant, timestamp_ms)
                if activated:
                    self._state.active_quadrant = activated
        finally:
            landmarker.close()
            cap.release()
