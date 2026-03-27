# tests/test_statusline_wrapper.py
"""Tests for statusline wrapper logic."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from eyeclaude.statusline_wrapper import build_indicator, STATUS_DIR


class TestBuildIndicator:
    def test_idle_status(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "idle", "active": False}))
        result = build_indicator(status_file)
        assert result == "\U0001f7e2"  # green circle

    def test_working_status(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "working", "active": False}))
        result = build_indicator(status_file)
        assert result == "\U0001f535"  # blue circle

    def test_finished_status(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "finished", "active": False}))
        result = build_indicator(status_file)
        assert result == "\U0001f7e1"  # yellow circle

    def test_error_status(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "error", "active": False}))
        result = build_indicator(status_file)
        assert result == "\U0001f534"  # red circle

    def test_active_indicator(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text(json.dumps({"status": "idle", "active": True}))
        result = build_indicator(status_file)
        assert result == "\U0001f7e2\u25c0"  # green circle + left pointer

    def test_missing_file_returns_empty(self, tmp_path):
        status_file = tmp_path / "nonexistent.json"
        result = build_indicator(status_file)
        assert result == ""

    def test_corrupt_json_returns_empty(self, tmp_path):
        status_file = tmp_path / "1001.json"
        status_file.write_text("not json")
        result = build_indicator(status_file)
        assert result == ""
