"""Tests for config loading, default merging, and validation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from src.config import load_config, _deep_merge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, content: str, name: str = "config.yml") -> Path:
    """Write YAML content to a temp file and return the path."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"audio": {"denoise": True, "loudness_target": -14}}
        override = {"audio": {"loudness_target": -16}}
        result = _deep_merge(base, override)
        assert result["audio"]["denoise"] is True
        assert result["audio"]["loudness_target"] == -16

    def test_base_not_mutated(self):
        base = {"a": {"x": 1}}
        override = {"a": {"x": 99}}
        _deep_merge(base, override)
        assert base["a"]["x"] == 1  # original unchanged

    def test_new_key_in_override(self):
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 2}

    def test_override_replaces_non_dict_with_dict(self):
        base = {"key": "string_value"}
        override = {"key": {"nested": True}}
        result = _deep_merge(base, override)
        assert result["key"] == {"nested": True}


# ---------------------------------------------------------------------------
# load_config — defaults only
# ---------------------------------------------------------------------------

class TestLoadConfigDefaults:
    def test_loads_without_user_config(self):
        config = load_config()
        assert "whisper" in config
        assert "audio" in config
        assert "video" in config
        assert "encoding" in config

    def test_default_whisper_model(self):
        config = load_config()
        assert config["whisper"]["model"] == "large-v3"

    def test_default_loudness_target(self):
        config = load_config()
        assert config["audio"]["loudness_target"] == -14

    def test_default_codec(self):
        config = load_config()
        assert config["encoding"]["codec"] == "h264_videotoolbox"

    def test_default_zoom_factor(self):
        config = load_config()
        assert config["video"]["zoom_punch"]["zoom_factor"] == 1.05

    def test_default_filler_words_en(self):
        config = load_config()
        assert "um" in config["fillers"]["words"]["en"]
        assert "uh" in config["fillers"]["words"]["en"]

    def test_default_filler_words_ru(self):
        config = load_config()
        assert "ну" in config["fillers"]["words"]["ru"]


# ---------------------------------------------------------------------------
# load_config — user overrides
# ---------------------------------------------------------------------------

class TestLoadConfigWithUserFile:
    def test_user_override_merges_with_defaults(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            whisper:
              model: medium
              language: en
        """)
        config = load_config(user_config)
        assert config["whisper"]["model"] == "medium"
        assert config["whisper"]["language"] == "en"
        # Defaults from other sections still present
        assert "audio" in config

    def test_partial_override_preserves_other_keys(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            audio:
              loudness_target: -16
        """)
        config = load_config(user_config)
        assert config["audio"]["loudness_target"] == -16
        # Other audio keys still have defaults
        assert config["audio"]["denoise"] is True

    def test_lut_path_override(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            video:
              lut_path: /path/to/cinematic.cube
        """)
        config = load_config(user_config)
        assert config["video"]["lut_path"] == "/path/to/cinematic.cube"

    def test_missing_config_file_raises(self, tmp_path):
        missing = tmp_path / "nonexistent.yml"
        with pytest.raises(FileNotFoundError):
            load_config(missing)

    def test_empty_user_config_uses_defaults(self, tmp_path):
        user_config = _write_yaml(tmp_path, "")
        config = load_config(user_config)
        assert config["whisper"]["model"] == "large-v3"


# ---------------------------------------------------------------------------
# load_config — validation
# ---------------------------------------------------------------------------

class TestConfigValidation:
    def test_invalid_whisper_model_raises(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            whisper:
              model: gpt-4-turbo
        """)
        with pytest.raises(ValueError, match="Invalid whisper.model"):
            load_config(user_config)

    def test_valid_whisper_models(self, tmp_path):
        for model in ("tiny", "base", "small", "medium", "large", "large-v2", "large-v3"):
            user_config = _write_yaml(tmp_path, f"whisper:\n  model: {model}")
            config = load_config(user_config)
            assert config["whisper"]["model"] == model

    def test_loudness_target_too_low_raises(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            audio:
              loudness_target: -80
        """)
        with pytest.raises(ValueError, match="loudness_target"):
            load_config(user_config)

    def test_loudness_target_too_high_raises(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            audio:
              loudness_target: 5
        """)
        with pytest.raises(ValueError, match="loudness_target"):
            load_config(user_config)

    def test_zoom_factor_below_1_raises(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            video:
              zoom_punch:
                zoom_factor: 0.9
        """)
        with pytest.raises(ValueError, match="zoom_factor"):
            load_config(user_config)

    def test_zoom_factor_above_2_raises(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            video:
              zoom_punch:
                zoom_factor: 2.5
        """)
        with pytest.raises(ValueError, match="zoom_factor"):
            load_config(user_config)

    def test_encoding_quality_out_of_range_raises(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            encoding:
              quality: 110
        """)
        with pytest.raises(ValueError, match="quality"):
            load_config(user_config)

    def test_encoding_quality_zero_is_valid(self, tmp_path):
        user_config = _write_yaml(tmp_path, """
            encoding:
              quality: 0
        """)
        config = load_config(user_config)
        assert config["encoding"]["quality"] == 0
