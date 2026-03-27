# tests/test_calibration_overlay.py
"""Tests for calibration overlay logic (non-GUI)."""

import pytest
from eyeclaude.calibration_overlay import CalibrationState, TerminalRect


class TestTerminalRect:
    def test_contains_point_inside(self):
        rect = TerminalRect(hwnd=1, label="T1", left=100, top=100, right=500, bottom=400)
        assert rect.contains(300, 250)

    def test_contains_point_outside(self):
        rect = TerminalRect(hwnd=1, label="T1", left=100, top=100, right=500, bottom=400)
        assert not rect.contains(50, 50)

    def test_contains_point_on_edge(self):
        rect = TerminalRect(hwnd=1, label="T1", left=100, top=100, right=500, bottom=400)
        assert rect.contains(100, 100)


class TestCalibrationState:
    def test_initial_state(self):
        state = CalibrationState()
        assert state.selected_hwnd is None
        assert state.recording is False
        assert state.calibrated_hwnds == set()

    def test_select_terminal(self):
        state = CalibrationState()
        state.select(hwnd=1001)
        assert state.selected_hwnd == 1001
        assert state.recording is False

    def test_start_recording(self):
        state = CalibrationState()
        state.select(hwnd=1001)
        state.start_recording()
        assert state.recording is True
        assert len(state.samples) == 0

    def test_add_sample(self):
        state = CalibrationState()
        state.select(hwnd=1001)
        state.start_recording()
        state.add_sample(0.5, 0.3)
        assert len(state.samples) == 1
        assert state.samples[0] == (0.5, 0.3)

    def test_stop_recording_returns_samples(self):
        state = CalibrationState()
        state.select(hwnd=1001)
        state.start_recording()
        state.add_sample(0.5, 0.3)
        state.add_sample(0.6, 0.4)
        samples = state.stop_recording()
        assert len(samples) == 2
        assert state.recording is False
        assert 1001 in state.calibrated_hwnds

    def test_stop_recording_without_start(self):
        state = CalibrationState()
        samples = state.stop_recording()
        assert samples == []

    def test_cannot_add_sample_when_not_recording(self):
        state = CalibrationState()
        state.add_sample(0.5, 0.3)
        assert len(state.samples) == 0
