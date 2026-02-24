"""YAML config loader with validation and defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Path to the bundled default config
_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.default.yml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load pipeline configuration.

    Starts from config.default.yml, then merges the user-provided config on top.
    If config_path is None, only the defaults are used.

    Returns the merged config dict.
    Raises ValueError if the config file cannot be parsed.
    """
    with open(_DEFAULT_CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    if config_path is not None:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path) as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)

    _validate(config)
    return config


def _validate(config: dict[str, Any]) -> None:
    """Validate the merged config. Raises ValueError on invalid values."""
    whisper_models = {"tiny", "base", "small", "medium", "large", "large-v2", "large-v3"}
    model = config.get("whisper", {}).get("model", "")
    if model not in whisper_models:
        raise ValueError(
            f"Invalid whisper.model '{model}'. Must be one of: {', '.join(sorted(whisper_models))}"
        )

    loudness_target = config.get("audio", {}).get("loudness_target", -14)
    if not (-70 <= loudness_target <= 0):
        raise ValueError(f"audio.loudness_target must be between -70 and 0 dB, got {loudness_target}")

    zoom_factor = config.get("video", {}).get("zoom_punch", {}).get("zoom_factor", 1.05)
    if not (1.0 <= zoom_factor <= 2.0):
        raise ValueError(f"video.zoom_punch.zoom_factor must be between 1.0 and 2.0, got {zoom_factor}")

    quality = config.get("encoding", {}).get("quality", 65)
    if not (0 <= quality <= 100):
        raise ValueError(f"encoding.quality must be between 0 and 100, got {quality}")


def get_openrouter_api_key() -> str | None:
    """Return the OpenRouter API key from the environment, or None if not set."""
    return os.environ.get("OPENROUTER_API_KEY") or None
