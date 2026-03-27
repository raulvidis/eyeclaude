"""Tests for terminal auto-discovery."""

import pytest
from unittest.mock import patch, MagicMock

from eyeclaude.terminal_discovery import discover_terminals, get_window_rect, DiscoveredTerminal


class TestDiscoverTerminals:
    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_finds_cascadia_windows(self, mock_gui):
        """EnumWindows finds visible CASCADIA windows."""
        mock_gui.IsWindowVisible.return_value = True
        mock_gui.GetClassName.return_value = "CASCADIA_HOSTING_WINDOW_CLASS"
        mock_gui.GetWindowRect.return_value = (0, 0, 960, 540)
        mock_gui.GetWindowText.return_value = "Windows Terminal"

        def fake_enum(callback, _):
            callback(1001, None)
            callback(1002, None)
            return True
        mock_gui.EnumWindows.side_effect = fake_enum

        result = discover_terminals()
        assert len(result) == 2
        assert result[0].hwnd == 1001
        assert result[1].hwnd == 1002

    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_skips_invisible_windows(self, mock_gui):
        """Invisible windows are ignored."""
        mock_gui.IsWindowVisible.return_value = False
        mock_gui.GetClassName.return_value = "CASCADIA_HOSTING_WINDOW_CLASS"

        def fake_enum(callback, _):
            callback(1001, None)
            return True
        mock_gui.EnumWindows.side_effect = fake_enum

        result = discover_terminals()
        assert len(result) == 0

    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_skips_non_terminal_windows(self, mock_gui):
        """Non-terminal windows are ignored."""
        mock_gui.IsWindowVisible.return_value = True
        mock_gui.GetClassName.return_value = "Chrome_WidgetWin_1"

        def fake_enum(callback, _):
            callback(1001, None)
            return True
        mock_gui.EnumWindows.side_effect = fake_enum

        result = discover_terminals()
        assert len(result) == 0


class TestGetWindowRect:
    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_returns_rect(self, mock_gui):
        mock_gui.GetWindowRect.return_value = (100, 200, 500, 700)
        rect = get_window_rect(1001)
        assert rect == (100, 200, 500, 700)

    @patch("eyeclaude.terminal_discovery.win32gui")
    def test_returns_none_on_invalid_hwnd(self, mock_gui):
        mock_gui.GetWindowRect.side_effect = Exception("Invalid handle")
        rect = get_window_rect(9999)
        assert rect is None
