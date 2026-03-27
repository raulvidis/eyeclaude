from unittest.mock import patch, MagicMock

from eyeclaude.shared_state import SharedState, Quadrant, InstanceStatus
from eyeclaude.window_manager import WindowManager


class TestWindowManager:
    def test_focus_switches_on_new_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_LEFT)
            mock_focus.assert_called_once_with(111)

    def test_no_switch_when_same_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_LEFT)
            manager.update_focus(Quadrant.TOP_LEFT)
            assert mock_focus.call_count == 1

    def test_switch_to_different_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        state.register_terminal(pid=2, window_handle=222, quadrant=Quadrant.TOP_RIGHT)
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_LEFT)
            manager.update_focus(Quadrant.TOP_RIGHT)
            assert mock_focus.call_count == 2
            mock_focus.assert_called_with(222)

    def test_no_switch_when_no_terminal_in_quadrant(self):
        state = SharedState()
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_LEFT)
            mock_focus.assert_not_called()

    def test_none_quadrant_does_nothing(self):
        state = SharedState()
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(None)
            mock_focus.assert_not_called()
