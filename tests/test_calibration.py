import numpy as np

from eyeclaude.calibration import save_calibration, load_calibration
from eyeclaude.eye_tracker import CalibrationData, fit_affine


class TestCalibrationPersistence:
    def test_save_and_load_round_trip(self, tmp_path):
        path = tmp_path / "calibration.json"
        samples = [(0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7), (0.5, 0.5)]
        targets = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.5, 0.5)]
        affine = fit_affine(samples, targets)
        data = CalibrationData(
            affine=affine,
            points={
                "top_left": (0.3, 0.3),
                "top_right": (0.7, 0.3),
                "bottom_right": (0.7, 0.7),
                "bottom_left": (0.3, 0.7),
                "center": (0.5, 0.5),
            },
        )
        save_calibration(data, path)
        loaded = load_calibration(path)

        assert loaded.is_valid()
        np.testing.assert_allclose(loaded.affine, affine, atol=1e-9)
        assert loaded.points["top_left"] == (0.3, 0.3)
        assert len(loaded.points) == 5

    def test_load_missing_file_returns_empty(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        data = load_calibration(path)
        assert not data.is_valid()
        assert len(data.points) == 0

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json{{{")
        data = load_calibration(path)
        assert not data.is_valid()
        assert len(data.points) == 0

    def test_load_legacy_without_affine(self, tmp_path):
        path = tmp_path / "legacy.json"
        path.write_text('{"points": {"top_left": [0.1, 0.1]}}')
        data = load_calibration(path)
        assert not data.is_valid()
        assert data.points["top_left"] == (0.1, 0.1)
