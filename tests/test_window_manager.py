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

    def test_no_switch_when_unregistered_window_focused(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        manager = WindowManager(state)

        # Foreground window is 999 — not a registered terminal
        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus, \
             self._patch_foreground(999):
            manager.update_focus(Quadrant.TOP_LEFT)
            mock_focus.assert_not_called()

    def test_resumes_when_registered_window_refocused(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        state.register_terminal(pid=2, window_handle=222, quadrant=Quadrant.TOP_RIGHT)
        manager = WindowManager(state)

        # First, focus a registered window
        with patch("eyeclaude.window_manager.set_foreground_window"), \
             self._patch_foreground(111):
            manager.update_focus(Quadrant.TOP_LEFT)

        # Alt-tab away — should not switch
        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus, \
             self._patch_foreground(999):
            manager.update_focus(Quadrant.TOP_RIGHT)
            mock_focus.assert_not_called()

        # Come back — should switch now
        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus, \
             self._patch_foreground(111):
            manager.update_focus(Quadrant.TOP_RIGHT)
            mock_focus.assert_called_once_with(222)
