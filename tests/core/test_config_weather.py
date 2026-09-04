"""Configuration coverage for the native weather tool."""

from __future__ import annotations

from openjarvis.core.config import load_config


def test_weather_tool_config_loads_from_nested_toml(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[tools]
enabled = "get_weather"

[tools.weather]
provider = "openweathermap"
default_location = "Vienna,AT"
units = "imperial"
lang = "de"
""".strip(),
        encoding="utf-8",
    )
    load_config.cache_clear()
    try:
        config = load_config(config_path)
    finally:
        load_config.cache_clear()

    assert config.tools.enabled == "get_weather"
    assert config.tools.weather.provider == "openweathermap"
    assert config.tools.weather.default_location == "Vienna,AT"
    assert config.tools.weather.units == "imperial"
    assert config.tools.weather.lang == "de"
