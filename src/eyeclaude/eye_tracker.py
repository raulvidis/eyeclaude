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

# Eye corner landmarks for relative gaze calculation
# Left eye (from camera's perspective)
LEFT_EYE_OUTER = 33
LEFT_EYE_INNER = 133
LEFT_EYE_TOP = 159
LEFT_EYE_BOTTOM = 145

# Right eye (from camera's perspective)
RIGHT_EYE_OUTER = 362
RIGHT_EYE_INNER = 263
RIGHT_EYE_TOP = 386
RIGHT_EYE_BOTTOM = 374

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
    """Extract gaze direction using amplified iris-nose offset + head pose.

    The iris-to-nose offset captures where you're looking independent of
    head position. We amplify this offset and add it to the nose position
    (which captures head turns). Small eye movements get multiplied into
    large quadrant-distinguishing signals.

    Returns (x, y) where the values represent relative gaze direction.
    """
    try:
        # Nose tip (landmark 1) tracks head pose
        nose = landmarks[1]

        # Average iris position from both eyes
        l_iris = landmarks[LEFT_IRIS_CENTER]
        r_iris = landmarks[RIGHT_IRIS_CENTER]
        iris_x = (l_iris.x + r_iris.x) / 2

        # X: iris offset from nose (amplified, negated). Negated because
        # cv2.flip mirrors the frame — looking right moves iris right in
        # the flipped image but should decrease gaze_x (screen-left = 0).
        offset_x = -(iris_x - nose.x)
        amp_x = 8.0
        gaze_x = nose.x + offset_x * amp_x

        # Y: nose position only — vertical gaze is dominated by head tilt,
        # not iris movement (iris barely moves up/down in the socket).
        # nose.y tracks head tilt naturally in 0-1 image space.
        gaze_y = nose.y

        return (gaze_x, gaze_y)
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
        self._cap = None
        self._landmarker = None

    def start(self) -> None:
        """Open webcam on main thread, then start tracking in background."""
        self._cap = cv2.VideoCapture(self._webcam_index)
        if not self._cap.isOpened():
            logger.error("Cannot open webcam %d", self._webcam_index)
            return

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        model_path = ensure_model()
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

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
                    landmarks = result.face_landmarks[0]
                    gaze = _get_iris_center(landmarks)

                timestamp_ms = time.monotonic() * 1000
                quadrant = None
                if gaze and self._calibration.points:
                    quadrant = map_gaze_to_quadrant(gaze, self._calibration)

                activated = self._dwell.update(quadrant, timestamp_ms)
                if activated:
                    self._state.active_quadrant = activated
        except Exception as e:
            logger.error("Eye tracker error: %s", e)
