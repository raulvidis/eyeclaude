"""Configuration loading and persistence for EyeClaude."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".eyeclaude"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"

DEFAULT_BORDER_COLORS = {
    "idle": "#00FF00",
    "working": "#0088FF",
    "finished": "#FFD700",
    "error": "#FF0000",
}


@dataclass
class EyeClaudeConfig:
    dwell_time_ms: int = 400
    border_thickness_px: int = 4
    border_colors: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BORDER_COLORS))
    finished_flash_duration_ms: int = 2000
    webcam_index: int = 0


DEFAULT_CONFIG = EyeClaudeConfig()


def save_config(config: EyeClaudeConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2))


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> EyeClaudeConfig:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return EyeClaudeConfig()

    if not isinstance(data, dict):
        return EyeClaudeConfig()

    # Merge partial border_colors over the defaults so that a file that
    # specifies only some color keys doesn't replace the whole dict.
    if "border_colors" in data and isinstance(data["border_colors"], dict):
        merged = dict(DEFAULT_BORDER_COLORS)
        merged.update(data["border_colors"])
        data = dict(data)
        data["border_colors"] = merged

    return EyeClaudeConfig(**{
        k: v for k, v in data.items()
        if k in EyeClaudeConfig.__dataclass_fields__
    })
