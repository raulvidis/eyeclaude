import math

import numpy as np
import pytest

from eyeclaude.eye_tracker import (
    CalibrationData,
    DwellTracker,
    OneEuroFilter,
    fit_affine,
    map_gaze_to_quadrant,
)
from eyeclaude.shared_state import Quadrant


def _identity_calibration() -> CalibrationData:
    """Calibration where raw gaze == normalized screen coords."""
    samples = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.5, 0.5)]
    targets = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.5, 0.5)]
    return CalibrationData(affine=fit_affine(samples, targets))


class TestMapGazeToQuadrant:
    def setup_method(self):
        self.calibration = _identity_calibration()

    def test_top_left(self):
        assert map_gaze_to_quadrant((0.2, 0.2), self.calibration) == Quadrant.TOP_LEFT

    def test_top_right(self):
        assert map_gaze_to_quadrant((0.8, 0.2), self.calibration) == Quadrant.TOP_RIGHT

    def test_bottom_left(self):
        assert map_gaze_to_quadrant((0.2, 0.8), self.calibration) == Quadrant.BOTTOM_LEFT

    def test_bottom_right(self):
        assert map_gaze_to_quadrant((0.8, 0.8), self.calibration) == Quadrant.BOTTOM_RIGHT


class TestFitAffine:
    def test_identity_recovers(self):
        samples = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        targets = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        A = fit_affine(samples, targets)
        np.testing.assert_allclose(A, np.array([[1, 0, 0], [0, 1, 0]]), atol=1e-9)

    def test_translation_and_scale(self):
        # raw range [0.3, 0.7] should map to [0, 1]
        samples = [(0.3, 0.3), (0.7, 0.3), (0.3, 0.7), (0.7, 0.7), (0.5, 0.5)]
        targets = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)]
        A = fit_affine(samples, targets)
        cd = CalibrationData(affine=A)
        sx, sy = cd.gaze_to_screen_norm(0.5, 0.5)
        assert math.isclose(sx, 0.5, abs_tol=1e-6)
        assert math.isclose(sy, 0.5, abs_tol=1e-6)
        sx, sy = cd.gaze_to_screen_norm(0.3, 0.3)
        assert math.isclose(sx, 0.0, abs_tol=1e-6)
        assert math.isclose(sy, 0.0, abs_tol=1e-6)

    def test_rejects_too_few_points(self):
        with pytest.raises(ValueError):
            fit_affine([(0, 0), (1, 1)], [(0, 0), (1, 1)])

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError):
            fit_affine([(0, 0), (1, 1), (2, 2)], [(0, 0)])


class TestCalibrationData:
    def test_invalid_when_no_affine(self):
        cd = CalibrationData()
        assert not cd.is_valid()

    def test_clamps_to_unit_square(self):
        cd = _identity_calibration()
        sx, sy = cd.gaze_to_screen_norm(2.0, -3.0)
        assert sx == 1.0
        assert sy == 0.0


class TestOneEuroFilter:
    def test_first_sample_passes_through(self):
        f = OneEuroFilter()
        assert f.filter(0.5, t=0.0) == 0.5

    def test_smooths_constant_signal(self):
        f = OneEuroFilter(mincutoff=1.0, beta=0.0)
        f.filter(0.5, t=0.0)
        # Constant signal should remain near 0.5
        out = f.filter(0.5, t=0.033)
        assert math.isclose(out, 0.5, abs_tol=1e-6)

    def test_reset_clears_state(self):
        f = OneEuroFilter()
        f.filter(0.5, t=0.0)
        f.reset()
        # After reset, next sample should pass through again
        assert f.filter(0.9, t=0.0) == 0.9


class TestDwellTracker:
    def test_no_dwell_on_first_gaze(self):
        tracker = DwellTracker(dwell_time_ms=400)
        assert tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0) is None

    def test_dwell_activates_after_duration(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        result = tracker.update(Quadrant.TOP_LEFT, timestamp_ms=500)
        assert result == Quadrant.TOP_LEFT

    def test_dwell_resets_on_quadrant_change(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=300)
        assert tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=600) is None

    def test_dwell_activates_after_reset_and_enough_time(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=300)
        result = tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=800)
        assert result == Quadrant.TOP_RIGHT

    def test_none_gaze_does_not_activate(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        assert tracker.update(None, timestamp_ms=500) is None

    def test_does_not_re_trigger_same_quadrant(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=500)
        assert tracker.update(Quadrant.TOP_LEFT, timestamp_ms=1000) is None
