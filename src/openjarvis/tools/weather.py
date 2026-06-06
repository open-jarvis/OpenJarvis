"""Weather tool — current conditions and short forecast.

Uses the free, key-free Open-Meteo API by default (geocoding + forecast), so it
works out of the box with no configuration. No API key is required.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 15.0
_MAX_FORECAST_DAYS = 7

# WMO weather interpretation codes → human-readable description.
_WMO_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _describe(code: Any) -> str:
    try:
        return _WMO_CODES.get(int(code), f"Unknown (code {code})")
    except (TypeError, ValueError):
        return "Unknown"


@ToolRegistry.register("weather")
class WeatherTool(BaseTool):
    """Look up current weather and a short forecast for a location."""

    tool_id = "weather"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="weather",
            description=(
                "Get current weather and an optional multi-day forecast for a"
                " place (city, town, or 'City, Country'). No API key required."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Place name, e.g. 'Austin' or 'Paris, FR'.",
                    },
                    "units": {
                        "type": "string",
                        "description": (
                            "'imperial' (Fahrenheit/mph) or 'metric'"
                            " (Celsius/km·h). Default: imperial."
                        ),
                    },
                    "days": {
                        "type": "integer",
                        "description": (
                            "Forecast days to include (0-7). 0 = current only."
                            " Default: 0."
                        ),
                    },
                },
                "required": ["location"],
            },
            category="information",
            metadata={"provider": "open-meteo", "requires_api_key": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        location = str(params.get("location", "")).strip()
        if not location:
            return ToolResult(
                tool_name="weather",
                content="No location provided.",
                success=False,
            )

        units = str(params.get("units", "imperial")).strip().lower()
        if units not in ("imperial", "metric"):
            units = "imperial"
        imperial = units == "imperial"

        try:
            days = int(params.get("days", 0) or 0)
        except (TypeError, ValueError):
            days = 0
        days = max(0, min(days, _MAX_FORECAST_DAYS))

        try:
            import httpx
        except ImportError:
            return ToolResult(
                tool_name="weather",
                content="httpx is not installed. Install with: pip install httpx",
                success=False,
            )

        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                place = self._geocode(client, location)
                if place is None:
                    return ToolResult(
                        tool_name="weather",
                        content=f"Could not find a location named '{location}'.",
                        success=False,
                    )
                data = self._forecast(client, place, imperial=imperial, days=days)
        except Exception as exc:  # network/HTTP/parse failures
            logger.debug("weather lookup failed: %s", exc)
            return ToolResult(
                tool_name="weather",
                content=f"Weather lookup failed: {exc}",
                success=False,
            )

        return ToolResult(
            tool_name="weather",
            content=self._format(place, data, imperial=imperial, days=days),
            success=True,
            metadata={
                "location": place["label"],
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "units": units,
            },
        )

    @staticmethod
    def _geocode(client: Any, location: str) -> Dict[str, Any] | None:
        resp = client.get(
            _GEOCODE_URL,
            params={"name": location, "count": 1, "language": "en", "format": "json"},
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            return None
        top = results[0]
        label_parts = [top.get("name", location)]
        if top.get("admin1"):
            label_parts.append(top["admin1"])
        if top.get("country"):
            label_parts.append(top["country"])
        return {
            "label": ", ".join(label_parts),
            "latitude": top["latitude"],
            "longitude": top["longitude"],
        }

    @staticmethod
    def _forecast(
        client: Any, place: Dict[str, Any], *, imperial: bool, days: int
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "wind_speed_10m,weather_code"
            ),
            "temperature_unit": "fahrenheit" if imperial else "celsius",
            "wind_speed_unit": "mph" if imperial else "kmh",
            "timezone": "auto",
        }
        if days > 0:
            params["daily"] = (
                "temperature_2m_max,temperature_2m_min,weather_code"
            )
            params["forecast_days"] = days
        resp = client.get(_FORECAST_URL, params=params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _format(
        place: Dict[str, Any],
        data: Dict[str, Any],
        *,
        imperial: bool,
        days: int,
    ) -> str:
        temp_unit = "°F" if imperial else "°C"
        wind_unit = "mph" if imperial else "km/h"
        lines: List[str] = [f"Weather for {place['label']}:"]

        cur = data.get("current") or {}
        if cur:
            lines.append(
                f"Now: {cur.get('temperature_2m')}{temp_unit}"
                f" ({_describe(cur.get('weather_code'))}),"
                f" feels like {cur.get('apparent_temperature')}{temp_unit},"
                f" humidity {cur.get('relative_humidity_2m')}%,"
                f" wind {cur.get('wind_speed_10m')} {wind_unit}."
            )

        daily = data.get("daily") or {}
        dates = daily.get("time") or []
        if days > 0 and dates:
            highs = daily.get("temperature_2m_max") or []
            lows = daily.get("temperature_2m_min") or []
            codes = daily.get("weather_code") or []
            lines.append("Forecast:")
            for i, date in enumerate(dates):
                hi = highs[i] if i < len(highs) else "?"
                lo = lows[i] if i < len(lows) else "?"
                code = codes[i] if i < len(codes) else None
                lines.append(
                    f"  {date}: {lo}{temp_unit}–{hi}{temp_unit},"
                    f" {_describe(code)}"
                )

        return "\n".join(lines)


__all__ = ["WeatherTool"]
