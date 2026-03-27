import json

from eyeclaude.calibration import save_calibration, load_calibration
from eyeclaude.eye_tracker import CalibrationData
from eyeclaude.shared_state import Quadrant


class TestCalibrationPersistence:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "calibration.json"
        data = CalibrationData(points={
            Quadrant.TOP_LEFT: (0.3, 0.3),
            Quadrant.TOP_RIGHT: (0.7, 0.3),
            Quadrant.BOTTOM_LEFT: (0.3, 0.7),
            Quadrant.BOTTOM_RIGHT: (0.7, 0.7),
        })
        save_calibration(data, path)
        loaded = load_calibration(path)
        assert loaded.points[Quadrant.TOP_LEFT] == (0.3, 0.3)
        assert loaded.points[Quadrant.BOTTOM_RIGHT] == (0.7, 0.7)
        assert len(loaded.points) == 4

    def test_load_missing_file_returns_empty(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        data = load_calibration(path)
        assert len(data.points) == 0

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json{{{")
        data = load_calibration(path)
        assert len(data.points) == 0
