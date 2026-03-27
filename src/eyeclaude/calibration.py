"""Calibration flow and persistence for EyeClaude."""

import json
import logging
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from eyeclaude.eye_tracker import CalibrationData, _get_iris_center
from eyeclaude.shared_state import Quadrant

logger = logging.getLogger(__name__)

DEFAULT_CALIBRATION_PATH = Path.home() / ".eyeclaude" / "calibration.json"

QUADRANT_ORDER = [
    Quadrant.TOP_LEFT,
    Quadrant.TOP_RIGHT,
    Quadrant.BOTTOM_LEFT,
    Quadrant.BOTTOM_RIGHT,
]

QUADRANT_LABELS = {
    Quadrant.TOP_LEFT: "TOP-LEFT",
    Quadrant.TOP_RIGHT: "TOP-RIGHT",
    Quadrant.BOTTOM_LEFT: "BOTTOM-LEFT",
    Quadrant.BOTTOM_RIGHT: "BOTTOM-RIGHT",
}


def save_calibration(data: CalibrationData, path: Path = DEFAULT_CALIBRATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = {q.value: list(pos) for q, pos in data.points.items()}
    path.write_text(json.dumps(serialized, indent=2))


def load_calibration(path: Path = DEFAULT_CALIBRATION_PATH) -> CalibrationData:
    try:
        raw = json.loads(path.read_text())
        points = {}
        for q in Quadrant:
            if q.value in raw:
                x, y = raw[q.value]
                points[q] = (float(x), float(y))
        return CalibrationData(points=points)
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return CalibrationData()


def _quadrant_screen_center(quadrant: Quadrant, screen_w: int, screen_h: int) -> tuple[int, int]:
    """Get the pixel center of a quadrant on screen."""
    half_w = screen_w // 2
    half_h = screen_h // 2
    centers = {
        Quadrant.TOP_LEFT: (half_w // 2, half_h // 2),
        Quadrant.TOP_RIGHT: (half_w + half_w // 2, half_h // 2),
        Quadrant.BOTTOM_LEFT: (half_w // 2, half_h + half_h // 2),
        Quadrant.BOTTOM_RIGHT: (half_w + half_w // 2, half_h + half_h // 2),
    }
    return centers[quadrant]


def run_calibration(webcam_index: int = 0) -> CalibrationData | None:
    """Run interactive calibration. Returns CalibrationData or None if cancelled."""
    import win32api
    import win32con

    screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

    cap = cv2.VideoCapture(webcam_index)
    if not cap.isOpened():
        logger.error("Cannot open webcam %d", webcam_index)
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    mp_face_mesh = mp.solutions.face_mesh
    calibration = CalibrationData()

    window_name = "EyeClaude Calibration"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    # Move and resize to fill the screen, then set topmost + fullscreen
    cv2.moveWindow(window_name, 0, 0)
    cv2.resizeWindow(window_name, screen_w, screen_h)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    # Show an initial black frame to make the window appear
    canvas = np.zeros((screen_h, screen_w, 3), dtype=np.uint8)
    cv2.putText(canvas, "Initializing webcam...", (screen_w // 2 - 200, screen_h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    cv2.imshow(window_name, canvas)
    cv2.waitKey(100)

    # Force the OpenCV window to the foreground on Windows 11
    import win32gui
    hwnd = win32gui.FindWindow(None, window_name)
    if hwnd:
        win32gui.SetForegroundWindow(hwnd)

    with mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as face_mesh:

        for quadrant in QUADRANT_ORDER:
            dot_x, dot_y = _quadrant_screen_center(quadrant, screen_w, screen_h)
            label = QUADRANT_LABELS[quadrant]
            collecting = True

            while collecting:
                ret, frame = cap.read()
                if not ret:
                    continue

                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)

                # Draw calibration screen
                canvas = np.zeros((screen_h, screen_w, 3), dtype=np.uint8)

                # Draw all dots
                for q in QUADRANT_ORDER:
                    dx, dy = _quadrant_screen_center(q, screen_w, screen_h)
                    color = (0, 255, 0) if q == quadrant else (80, 80, 80)
                    if q in calibration.points:
                        color = (255, 150, 0)
                    if q == quadrant:
                        color = (0, 255, 0)
                    cv2.circle(canvas, (dx, dy), 20, color, -1)

                # Instructions
                cv2.putText(
                    canvas,
                    f"Look at the GREEN dot ({label}) and press SPACE",
                    (screen_w // 2 - 350, screen_h - 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2,
                )
                cv2.putText(
                    canvas,
                    "Press ESC to cancel",
                    (screen_w // 2 - 150, screen_h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1,
                )

                cv2.imshow(window_name, canvas)
                key = cv2.waitKey(1) & 0xFF

                if key == 27:  # ESC
                    cap.release()
                    cv2.destroyAllWindows()
                    return None

                if key == 32:  # SPACE
                    if results.multi_face_landmarks:
                        landmarks = results.multi_face_landmarks[0].landmark
                        iris_pos = _get_iris_center(landmarks)
                        if iris_pos:
                            calibration.points[quadrant] = iris_pos
                            logger.info(f"Calibrated {label}: {iris_pos}")
                            collecting = False
                        else:
                            logger.warning("No iris detected — try again")
                    else:
                        logger.warning("No face detected — try again")

    cap.release()
    cv2.destroyAllWindows()

    save_calibration(calibration)
    return calibration
