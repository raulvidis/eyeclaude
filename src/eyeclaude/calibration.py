"""Calibration persistence for EyeClaude."""

import json
import logging
from pathlib import Path

import numpy as np

from eyeclaude.eye_tracker import CalibrationData

logger = logging.getLogger(__name__)

DEFAULT_CALIBRATION_PATH = Path.home() / ".eyeclaude" / "calibration.json"


def save_calibration(data: CalibrationData, path: Path = DEFAULT_CALIBRATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "affine": data.affine.tolist() if data.affine is not None else None,
        "points": {k: list(v) for k, v in data.points.items()},
    }
    path.write_text(json.dumps(payload, indent=2))


def load_calibration(path: Path = DEFAULT_CALIBRATION_PATH) -> CalibrationData:
    try:
        raw = json.loads(path.read_text())
        affine = None
        if raw.get("affine") is not None:
            affine = np.array(raw["affine"], dtype=np.float64)
            if affine.shape != (2, 3):
                logger.warning("Ignoring affine with bad shape %s", affine.shape)
                affine = None
        points = {k: (float(v[0]), float(v[1])) for k, v in raw.get("points", {}).items()}
        return CalibrationData(affine=affine, points=points)
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        return CalibrationData()
