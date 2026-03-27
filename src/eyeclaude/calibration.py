"""Calibration flow and persistence for EyeClaude."""

import json
import logging
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from eyeclaude.eye_tracker import CalibrationData, _get_iris_center, ensure_model
from eyeclaude.shared_state import Quadrant, SharedState

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


def run_calibration(
    webcam_index: int = 0,
    state: SharedState | None = None,
) -> CalibrationData | None:
    """Run calibration using registered terminal windows.

    If terminals are registered in state, highlights each terminal window
    in sequence and asks the user to look at it naturally for 3 seconds.
    This captures real-world gaze patterns instead of artificial dot-staring.

    Falls back to simple console-based calibration if no state/terminals.
    """
    model_path = ensure_model()
    cap = cv2.VideoCapture(webcam_index)
    if not cap.isOpened():
        logger.error("Cannot open webcam %d", webcam_index)
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

    # Check if we have registered terminals to calibrate with
    terminals = state.get_all_terminals() if state else []
    quadrants_to_calibrate = [t.quadrant for t in terminals]

    if not quadrants_to_calibrate:
        # No terminals registered — use all 4 quadrants with console prompts
        quadrants_to_calibrate = list(QUADRANT_ORDER)

    try:
        calibration = _run_terminal_calibration(
            cap, landmarker, quadrants_to_calibrate,
            terminals if terminals else None,
        )
    finally:
        landmarker.close()
        cap.release()

    if calibration and calibration.points:
        save_calibration(calibration)
        return calibration
    return None


def _run_terminal_calibration(
    cap,
    landmarker,
    quadrants: list[Quadrant],
    terminals: list | None,
) -> CalibrationData | None:
    """Calibrate by having the user look at each terminal naturally.

    For each quadrant:
    1. Flash the terminal window so the user knows which one to look at
    2. Collect gaze samples for 3 seconds
    3. Median-average the samples for that quadrant's calibration point
    """
    import win32con
    import win32gui
    import winsound

    calibration = CalibrationData()
    sample_duration = 3.0  # seconds per quadrant

    # Map quadrants to terminal HWNDs
    quadrant_hwnds = {}
    if terminals:
        for t in terminals:
            quadrant_hwnds[t.quadrant] = t.window_handle

    print()
    print("=== EyeClaude Calibration ===")
    print("Each terminal will flash and come to the foreground.")
    print("Look at it naturally as you would when working.")
    print("You'll hear a beep when sampling starts for each terminal.")
    print()

    for quadrant in quadrants:
        label = QUADRANT_LABELS[quadrant]
        hwnd = quadrant_hwnds.get(quadrant)

        # Save original title
        original_title = None
        if hwnd:
            try:
                original_title = win32gui.GetWindowText(hwnd)
            except Exception:
                pass

        # Bring the target terminal to the foreground so user can see it
        if hwnd:
            try:
                win32gui.SetWindowText(hwnd, f"=== LOOK AT THIS WINDOW === ({label})")
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                # Flash the window border to draw attention
                win32gui.FlashWindowEx(hwnd, 2, 5, 100)  # FLASHW_ALL, 5 flashes, 100ms
            except Exception:
                pass

        # Countdown
        print(f"  {label}: bringing window to front...")
        time.sleep(1.5)  # Give user time to see which window it is

        # Beep to signal "start looking now"
        try:
            winsound.Beep(800, 200)
        except Exception:
            pass

        print(f"  {label}: recording... look at it naturally")

        # Collect gaze samples
        samples_x = []
        samples_y = []
        start = time.monotonic()

        while time.monotonic() - start < sample_duration:
            ret, frame = cap.read()
            if not ret:
                continue

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect(mp_image)

            if result.face_landmarks:
                gaze = _get_iris_center(result.face_landmarks[0])
                if gaze:
                    samples_x.append(gaze[0])
                    samples_y.append(gaze[1])

            # Small sleep to avoid burning CPU
            time.sleep(0.03)

        # Done beep (lower pitch)
        try:
            winsound.Beep(400, 150)
        except Exception:
            pass

        # Restore original title
        if hwnd and original_title is not None:
            try:
                win32gui.SetWindowText(hwnd, original_title)
            except Exception:
                pass

        if len(samples_x) < 5:
            print(f"  Warning: Only got {len(samples_x)} samples for {label}.")
            print("  Make sure your face is visible to the webcam.")
            if len(samples_x) == 0:
                continue

        # Use the median to filter out outliers (blinks, glances away)
        avg_x = float(np.median(samples_x))
        avg_y = float(np.median(samples_y))
        calibration.points[quadrant] = (avg_x, avg_y)
        print(f"  Captured {len(samples_x)} samples -> ({avg_x:.4f}, {avg_y:.4f})")

        # Brief pause between quadrants
        time.sleep(0.5)

    print()
    if len(calibration.points) >= 2:
        print(f"Calibration complete! {len(calibration.points)} quadrants calibrated.")
        # Show spread to help diagnose issues
        xs = [p[0] for p in calibration.points.values()]
        ys = [p[1] for p in calibration.points.values()]
        print(f"  X range: {min(xs):.4f} - {max(xs):.4f} (spread: {max(xs)-min(xs):.4f})")
        print(f"  Y range: {min(ys):.4f} - {max(ys):.4f} (spread: {max(ys)-min(ys):.4f})")
    else:
        print("Calibration failed — not enough data.")
        return None

    return calibration
