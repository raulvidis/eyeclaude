from unittest.mock import patch, MagicMock

from eyeclaude.shared_state import SharedState, Quadrant, InstanceStatus
from eyeclaude.window_manager import WindowManager


class TestWindowManager:
    def _patch_foreground(self, hwnd):
        """Patch GetForegroundWindow to return a specific hwnd."""
        return patch("eyeclaude.window_manager.win32gui.GetForegroundWindow", return_value=hwnd)

    def test_focus_switches_on_new_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus, \
             self._patch_foreground(111):
            manager.update_focus(Quadrant.TOP_LEFT)
            mock_focus.assert_called_once_with(111)

    def test_no_switch_when_same_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus, \
             self._patch_foreground(111):
            manager.update_focus(Quadrant.TOP_LEFT)
            manager.update_focus(Quadrant.TOP_LEFT)
            assert mock_focus.call_count == 1

    def test_switch_to_different_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        state.register_terminal(pid=2, window_handle=222, quadrant=Quadrant.TOP_RIGHT)
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus, \
             self._patch_foreground(111):
            manager.update_focus(Quadrant.TOP_LEFT)
        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus, \
             self._patch_foreground(111):
            manager.update_focus(Quadrant.TOP_RIGHT)
            mock_focus.assert_called_once_with(222)

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

    def test_switches_even_when_unregistered_window_focused(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        manager = WindowManager(state)

        # Foreground window is 999 — not a registered terminal, but dwell
        # tracker already prevents accidental switches so we allow it
        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_LEFT)
            mock_focus.assert_called_once_with(111)

    def test_resumes_after_alt_tab(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        state.register_terminal(pid=2, window_handle=222, quadrant=Quadrant.TOP_RIGHT)
        manager = WindowManager(state)

        # Focus a registered window
        with patch("eyeclaude.window_manager.set_foreground_window"):
            manager.update_focus(Quadrant.TOP_LEFT)

        # Switch to different quadrant (even from unregistered foreground)
        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_RIGHT)
            mock_focus.assert_called_once_with(222)
