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

    def test_json_array_returns_default(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps([1, 2, 3]))
        config = load_config(config_path)
        assert config.dwell_time_ms == 400

    def test_json_number_returns_default(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(42))
        config = load_config(config_path)
        assert config.dwell_time_ms == 400

    def test_json_string_returns_default(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps("idle"))
        config = load_config(config_path)
        assert config.dwell_time_ms == 400


class TestBorderColorsMerge:
    def test_partial_border_colors_merged(self, tmp_path):
        """A file with only some border_colors keys merges over the defaults."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"border_colors": {"working": "#123456"}}))
        config = load_config(config_path)
        assert config.border_colors["idle"] == "#00FF00"
        assert config.border_colors["working"] == "#123456"
        assert config.border_colors["finished"] == "#FFD700"
        assert config.border_colors["error"] == "#FF0000"

    def test_full_border_colors_overrides_all(self, tmp_path):
        """A file with all four border_colors keys overrides all defaults."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "border_colors": {
                "idle": "#AABBCC",
                "working": "#112233",
                "finished": "#445566",
                "error": "#778899",
            }
        }))
        config = load_config(config_path)
        assert config.border_colors == {
            "idle": "#AABBCC",
            "working": "#112233",
            "finished": "#445566",
            "error": "#778899",
        }

    def test_absent_border_colors_yields_all_defaults(self, tmp_path):
        """A file with no border_colors key yields all four default colors."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"dwell_time_ms": 500}))
        config = load_config(config_path)
        assert config.border_colors == {
            "idle": "#00FF00",
            "working": "#0088FF",
            "finished": "#FFD700",
            "error": "#FF0000",
        }
