# tests/test_config.py
import json
import os
from pathlib import Path

import pytest

from eyeclaude.config import EyeClaudeConfig, load_config, save_config, DEFAULT_CONFIG


class TestDefaultConfig:
    def test_default_dwell_time(self):
        config = EyeClaudeConfig()
        assert config.dwell_time_ms == 400

    def test_default_border_thickness(self):
        config = EyeClaudeConfig()
        assert config.border_thickness_px == 4

    def test_default_border_colors(self):
        config = EyeClaudeConfig()
        assert config.border_colors == {
            "idle": "#00FF00",
            "working": "#0088FF",
            "finished": "#FFD700",
            "error": "#FF0000",
        }

    def test_default_finished_flash_duration(self):
        config = EyeClaudeConfig()
        assert config.finished_flash_duration_ms == 2000

    def test_default_webcam_index(self):
        config = EyeClaudeConfig()
        assert config.webcam_index == 0


class TestConfigPersistence:
    def test_save_and_load(self, tmp_path):
        config_path = tmp_path / "config.json"
        config = EyeClaudeConfig(dwell_time_ms=600, webcam_index=2)
        save_config(config, config_path)

        loaded = load_config(config_path)
        assert loaded.dwell_time_ms == 600
        assert loaded.webcam_index == 2
        assert loaded.border_thickness_px == 4  # default preserved

    def test_load_missing_file_returns_default(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        config = load_config(config_path)
        assert config.dwell_time_ms == 400

    def test_load_corrupt_file_returns_default(self, tmp_path):
        config_path = tmp_path / "bad.json"
        config_path.write_text("not valid json{{{")
        config = load_config(config_path)
        assert config.dwell_time_ms == 400
