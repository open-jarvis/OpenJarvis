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
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_DEFAULT_TOKEN_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "weather.json")


def _weather_api_get(url: str, params: Dict[str, str]) -> Dict[str, Any]:
    """Call an OpenWeatherMap API endpoint."""
    resp = httpx.get(url, params=params, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("weather")
class WeatherConnector(BaseConnector):
    """Fetch current weather and short-term forecast from OpenWeatherMap."""

    connector_id = "weather"
    display_name = "Weather"
    auth_type = "token"

    def __init__(self, *, token_path: str = _DEFAULT_TOKEN_PATH) -> None:
        self._token_path = Path(token_path)
        self._status = SyncStatus()

    def _load_config(self) -> Dict[str, str]:
        """Load API key and location from disk."""
        data = json.loads(self._token_path.read_text(encoding="utf-8"))
        return data

    def is_connected(self) -> bool:
        if not self._token_path.exists():
            return False
        try:
            data = json.loads(self._token_path.read_text(encoding="utf-8"))
            return bool(data.get("api_key"))
        except (json.JSONDecodeError, OSError):
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
        current = _weather_api_get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": location, "appid": api_key, "units": "imperial"},
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
        forecast = _weather_api_get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={
                "q": location,
                "appid": api_key,
                "units": "imperial",
                "cnt": "4",
            },
        )
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
