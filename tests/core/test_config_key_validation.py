"""Tests for config key validation."""

from __future__ import annotations

import pytest

from openjarvis.core.config import validate_config_key


class TestValidateConfigKey:
    def test_valid_engine_default(self):
        field_type = validate_config_key("engine.default")
        assert field_type is str

    def test_valid_engine_ollama_host(self):
        field_type = validate_config_key("engine.ollama.host")
        assert field_type is str

    def test_valid_intelligence_temperature(self):
        field_type = validate_config_key("intelligence.temperature")
        assert field_type is float

    def test_valid_intelligence_max_tokens(self):
        field_type = validate_config_key("intelligence.max_tokens")
        assert field_type is int

    def test_valid_agent_default_agent(self):
        field_type = validate_config_key("agent.default_agent")
        assert field_type is str

    def test_invalid_top_level_key(self):
        with pytest.raises(ValueError, match="Unknown config key"):
            validate_config_key("nonexistent.foo")

    def test_invalid_nested_key(self):
        with pytest.raises(ValueError, match="Unknown config key"):
            validate_config_key("engine.olllama.host")

    def test_invalid_leaf_key(self):
        with pytest.raises(ValueError, match="Unknown config key"):
            validate_config_key("engine.ollama.nonexistent")

    def test_empty_key(self):
        with pytest.raises(ValueError):
            validate_config_key("")

    def test_single_segment(self):
        with pytest.raises(ValueError):
            validate_config_key("engine")

    def test_hardware_key_rejected(self):
        """Hardware is auto-detected, not user-settable."""
        with pytest.raises(ValueError, match="Unknown config key"):
            validate_config_key("hardware.cpu_count")
