"""Weather connector — current conditions and forecast via OpenWeatherMap API.

Uses an API key stored in the connector config dir.
All API calls are in module-level functions for easy mocking in tests.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import ConnectorRegistry

_CURRENT_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
_STATUS_DETAILS = {
    400: "the request was invalid",
    401: "authentication failed",
    404: "the location was not found",
    429: "the provider rate limit was exceeded",
}


class WeatherAPIError(RuntimeError):
    """A credential-safe error returned by the OpenWeatherMap API."""


def _weather_api_get(url: str, params: Dict[str, str]) -> Dict[str, Any]:
    """Call an OpenWeatherMap API endpoint without leaking query credentials."""
    try:
        resp = httpx.get(url, params=params, timeout=30.0)
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPStatusError as exc:
        # The exception string contains the full request URL, including appid.
        # Never surface provider-controlled text: it could echo a query value.
        status = exc.response.status_code
        detail = _STATUS_DETAILS.get(status, "the request failed")
        raise WeatherAPIError(
            f"OpenWeatherMap returned HTTP {status}: {detail}"
        ) from None
    except httpx.RequestError:
        # RequestError also formats the request URL, so do not interpolate it.
        raise WeatherAPIError("OpenWeatherMap could not be reached") from None
    except (TypeError, ValueError):
        raise WeatherAPIError(
            "OpenWeatherMap returned an invalid JSON response"
        ) from None

    if not isinstance(payload, dict):
        raise WeatherAPIError("OpenWeatherMap returned an invalid response")
    return payload


def fetch_weather(
    *,
    api_key: str,
    location: str,
    units: str,
    language: str,
    include_forecast: bool = False,
    forecast_count: int = 8,
) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
    """Fetch weather for a caller-provided location from fixed API endpoints."""
    common_params = {
        "q": location,
        "appid": api_key,
        "units": units,
        "lang": language,
    }
    current = _weather_api_get(_CURRENT_WEATHER_URL, params=common_params)
    forecast = None
    if include_forecast:
        forecast = _weather_api_get(
            _FORECAST_URL,
            params={**common_params, "cnt": str(forecast_count)},
        )
    return current, forecast


@ConnectorRegistry.register("weather")
class WeatherConnector(BaseConnector):
    """Fetch current weather and short-term forecast from OpenWeatherMap."""

    connector_id = "weather"
    display_name = "Weather"
    auth_type = "token"

    def __init__(self, *, token_path: str | None = None) -> None:
        self._token_path = (
            Path(token_path)
            if token_path is not None
            else get_config_dir() / "connectors" / "weather.json"
        )
        self._status = SyncStatus()

    def _load_config(self) -> Dict[str, str]:
        """Load API key and location from disk."""
        data = json.loads(self._token_path.read_text(encoding="utf-8"))
        return data

    def stored_api_key(self) -> str | None:
        """Return the stored connector key, or ``None`` when unavailable."""
        try:
            value = self._load_config().get("api_key", "")
        except (AttributeError, json.JSONDecodeError, OSError, TypeError):
            return None
        value = str(value).strip()
        return value or None

    def configure(self, *, api_key: str, location: str) -> None:
        """Validate and persist the API key and required location."""
        api_key = api_key.strip()
        location = location.strip()
        if not api_key:
            raise ValueError("An OpenWeather API key is required")
        if not location:
            raise ValueError("A weather location is required")
        fetch_weather(
            api_key=api_key,
            location=location,
            units="imperial",
            language="en",
        )
        from openjarvis.security.file_utils import secure_write_json

        secure_write_json(
            self._token_path,
            {"api_key": api_key, "location": location},
        )

    def is_connected(self) -> bool:
        if not self._token_path.exists():
            return False
        try:
            data = json.loads(self._token_path.read_text(encoding="utf-8"))
            return bool(data.get("api_key"))
        except (AttributeError, json.JSONDecodeError, OSError, TypeError):
            return False

    def disconnect(self) -> None:
        if self._token_path.exists():
            self._token_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield Documents for current weather and forecast."""
        config = self._load_config()
        api_key = config["api_key"]
        location = config.get("location", "San Francisco,CA")

        # Current weather
        current, forecast = fetch_weather(
            api_key=api_key,
            location=location,
            units="imperial",
            language="en",
            include_forecast=True,
            forecast_count=4,
        )
        main = current.get("main", {})
        weather_desc = ", ".join(
            w.get("description", "") for w in current.get("weather", [])
        )
        content = (
            f"Temperature: {main.get('temp')}°F, "
            f"Conditions: {weather_desc}, "
            f"Humidity: {main.get('humidity')}%, "
            f"Wind: {current.get('wind', {}).get('speed')} mph"
        )
        yield Document(
            doc_id=f"weather-current-{location}",
            source="weather",
            doc_type="current",
            content=content,
            title=f"Current Weather — {location}",
            timestamp=datetime.now(),
            metadata={
                "location": location,
                "temp": main.get("temp"),
                "conditions": weather_desc,
                "humidity": main.get("humidity"),
                "wind_speed": current.get("wind", {}).get("speed"),
            },
        )

        # Forecast (next ~12 hours, 4 x 3-hour intervals)
        assert forecast is not None
        summaries = []
        for entry in forecast.get("list", []):
            dt_txt = entry.get("dt_txt", "")
            temp = entry.get("main", {}).get("temp")
            desc = ", ".join(w.get("description", "") for w in entry.get("weather", []))
            summaries.append(f"{dt_txt}: {temp}°F, {desc}")
        forecast_content = "Forecast:\n" + "\n".join(summaries)

        yield Document(
            doc_id=f"weather-forecast-{location}",
            source="weather",
            doc_type="forecast",
            content=forecast_content,
            title=f"Weather Forecast — {location}",
            timestamp=datetime.now(),
            metadata={"location": location},
        )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status


__all__ = ["WeatherAPIError", "WeatherConnector", "fetch_weather"]
