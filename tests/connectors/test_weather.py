"""Tests for WeatherConnector — OpenWeatherMap API."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


def test_weather_registered():
    """WeatherConnector is discoverable via ConnectorRegistry."""
    from openjarvis.connectors.weather import WeatherConnector

    ConnectorRegistry.register_value("weather", WeatherConnector)
    assert ConnectorRegistry.contains("weather")
    cls = ConnectorRegistry.get("weather")
    assert cls.connector_id == "weather"
    assert cls.display_name == "Weather"
    assert cls.auth_type == "token"


_CURRENT_RESPONSE = {
    "main": {"temp": 62.5, "humidity": 55},
    "weather": [{"description": "clear sky"}],
    "wind": {"speed": 8.2},
}

_FORECAST_RESPONSE = {
    "list": [
        {
            "dt_txt": "2026-04-02 12:00:00",
            "main": {"temp": 64.0},
            "weather": [{"description": "few clouds"}],
        },
        {
            "dt_txt": "2026-04-02 15:00:00",
            "main": {"temp": 66.0},
            "weather": [{"description": "scattered clouds"}],
        },
    ],
}


@pytest.fixture()
def connector(tmp_path):
    """WeatherConnector with fake config file."""
    from openjarvis.connectors.weather import WeatherConnector

    config_path = tmp_path / "weather.json"
    config_path.write_text(
        '{"api_key": "fake-key", "location": "San Francisco,CA"}',
        encoding="utf-8",
    )
    return WeatherConnector(token_path=str(config_path))


def test_is_connected(connector):
    assert connector.is_connected() is True


def test_is_connected_no_file(tmp_path):
    from openjarvis.connectors.weather import WeatherConnector

    c = WeatherConnector(token_path=str(tmp_path / "missing.json"))
    assert c.is_connected() is False


def test_sync_yields_two_documents(connector):
    """Sync returns one current weather and one forecast Document."""
    with patch(
        "openjarvis.connectors.weather._weather_api_get",
        side_effect=[_CURRENT_RESPONSE, _FORECAST_RESPONSE],
    ):
        docs = list(connector.sync())

    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)

    current = docs[0]
    assert current.source == "weather"
    assert current.doc_type == "current"
    assert "62.5" in current.content
    assert "clear sky" in current.content
    assert "55" in current.content

    forecast = docs[1]
    assert forecast.doc_type == "forecast"
    assert "64.0" in forecast.content


def test_disconnect(connector):
    connector.disconnect()
    assert connector.is_connected() is False
