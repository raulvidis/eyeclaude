from eyeclaude.eye_tracker import (
    map_gaze_to_quadrant,
    CalibrationData,
    DwellTracker,
)
from eyeclaude.shared_state import Quadrant


class TestMapGazeToQuadrant:
    def setup_method(self):
        # Simulated calibration: iris positions when looking at each quadrant center
        self.calibration = CalibrationData(
            points={
                Quadrant.TOP_LEFT: (0.3, 0.3),
                Quadrant.TOP_RIGHT: (0.7, 0.3),
                Quadrant.BOTTOM_LEFT: (0.3, 0.7),
                Quadrant.BOTTOM_RIGHT: (0.7, 0.7),
            }
        )

    def test_gaze_near_top_left(self):
        result = map_gaze_to_quadrant((0.32, 0.28), self.calibration)
        assert result == Quadrant.TOP_LEFT

    def test_gaze_near_top_right(self):
        result = map_gaze_to_quadrant((0.68, 0.31), self.calibration)
        assert result == Quadrant.TOP_RIGHT

    def test_gaze_near_bottom_left(self):
        result = map_gaze_to_quadrant((0.29, 0.72), self.calibration)
        assert result == Quadrant.BOTTOM_LEFT

    def test_gaze_near_bottom_right(self):
        result = map_gaze_to_quadrant((0.71, 0.69), self.calibration)
        assert result == Quadrant.BOTTOM_RIGHT

    def test_gaze_at_exact_calibration_point(self):
        result = map_gaze_to_quadrant((0.3, 0.3), self.calibration)
        assert result == Quadrant.TOP_LEFT

    def test_gaze_at_center_returns_nearest(self):
        # Dead center (0.5, 0.5) is equidistant from all — any quadrant is acceptable
        result = map_gaze_to_quadrant((0.5, 0.5), self.calibration)
        assert result in list(Quadrant)


class TestDwellTracker:
    def test_no_dwell_on_first_gaze(self):
        tracker = DwellTracker(dwell_time_ms=400)
        result = tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        assert result is None

    def test_dwell_activates_after_duration(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        result = tracker.update(Quadrant.TOP_LEFT, timestamp_ms=500)
        assert result == Quadrant.TOP_LEFT

    def test_dwell_resets_on_quadrant_change(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=300)
        result = tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=600)
        # 600 - 300 = 300ms, not enough yet
        assert result is None

    def test_dwell_activates_after_reset_and_enough_time(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=300)
        result = tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=800)
        # 800 - 300 = 500ms, enough
        assert result == Quadrant.TOP_RIGHT

    def test_none_gaze_does_not_activate(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        result = tracker.update(None, timestamp_ms=500)
        assert result is None

    def test_does_not_re_trigger_same_quadrant(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=500)  # activates
        result = tracker.update(Quadrant.TOP_LEFT, timestamp_ms=1000)
        # Should not re-trigger since we're already focused here
        assert result is None
