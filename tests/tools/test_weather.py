"""Tests for the weather tool (network mocked)."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.tools.weather import WeatherTool


class _Resp:
    def __init__(self, json_data):
        self._json = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json


class _Client:
    """Fake httpx.Client returning queued responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        self.calls.append((url, params))
        return self._responses.pop(0)


_GEO = _Resp(
    {
        "results": [
            {
                "name": "Austin",
                "admin1": "Texas",
                "country": "United States",
                "latitude": 30.27,
                "longitude": -97.74,
            }
        ]
    }
)


def test_spec():
    tool = WeatherTool()
    assert tool.spec.name == "weather"
    assert tool.spec.category == "information"


def test_missing_location():
    tool = WeatherTool()
    result = tool.execute(location="")
    assert result.success is False


def test_current_weather():
    forecast = _Resp(
        {
            "current": {
                "temperature_2m": 85,
                "relative_humidity_2m": 40,
                "apparent_temperature": 88,
                "wind_speed_10m": 5,
                "weather_code": 1,
            }
        }
    )
    client = _Client([_GEO, forecast])
    with patch("httpx.Client", return_value=client):
        result = WeatherTool().execute(location="Austin")
    assert result.success is True
    assert "Austin, Texas, United States" in result.content
    assert "85" in result.content
    assert "Mainly clear" in result.content
    assert result.metadata["units"] == "imperial"


def test_forecast_days():
    forecast = _Resp(
        {
            "current": {
                "temperature_2m": 20,
                "relative_humidity_2m": 50,
                "apparent_temperature": 19,
                "wind_speed_10m": 8,
                "weather_code": 61,
            },
            "daily": {
                "time": ["2026-06-06", "2026-06-07"],
                "temperature_2m_max": [22, 25],
                "temperature_2m_min": [12, 14],
                "weather_code": [3, 0],
            },
        }
    )
    client = _Client([_GEO, forecast])
    with patch("httpx.Client", return_value=client):
        result = WeatherTool().execute(location="Austin", units="metric", days=2)
    assert result.success is True
    assert "Forecast:" in result.content
    assert "2026-06-06" in result.content
    assert "°C" in result.content
    # forecast request should have asked for daily fields
    _, forecast_params = client.calls[1]
    assert forecast_params["forecast_days"] == 2
    assert forecast_params["temperature_unit"] == "celsius"


def test_location_not_found():
    client = _Client([_Resp({"results": []})])
    with patch("httpx.Client", return_value=client):
        result = WeatherTool().execute(location="Nowheresville123")
    assert result.success is False
    assert "Could not find" in result.content
