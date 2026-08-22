"""Native, parameterized weather tool backed by OpenWeatherMap."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from openjarvis.connectors.weather import (
    WeatherAPIError,
    WeatherConnector,
    fetch_weather,
)
from openjarvis.core.credentials import get_tool_credential
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_TOOL_NAME = "get_weather"
_API_KEY_ENV = "OPENWEATHERMAP_API_KEY"
_VALID_UNITS = frozenset({"metric", "imperial"})
_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2}(?:_[a-z]{2})?$")
_MAX_LOCATION_LENGTH = 200
_MIN_FORECAST_HOURS = 3
_MAX_FORECAST_HOURS = 120


def _weather_description(payload: dict[str, Any]) -> str:
    weather = payload.get("weather")
    if not isinstance(weather, list):
        return ""
    descriptions = []
    for entry in weather:
        if isinstance(entry, dict):
            description = str(entry.get("description", "")).strip()
            if description:
                descriptions.append(description)
    return ", ".join(descriptions)


def _utc_timestamp(value: Any, fallback: Any = "") -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            pass
    return str(fallback or "")


def _structured_conditions(payload: dict[str, Any]) -> dict[str, Any]:
    main = payload.get("main")
    wind = payload.get("wind")
    rain = payload.get("rain")
    snow = payload.get("snow")
    if not isinstance(main, dict):
        main = {}
    if not isinstance(wind, dict):
        wind = {}
    if not isinstance(rain, dict):
        rain = {}
    if not isinstance(snow, dict):
        snow = {}
    return {
        "time": _utc_timestamp(payload.get("dt"), payload.get("dt_txt")),
        "temperature": main.get("temp"),
        "feels_like": main.get("feels_like"),
        "temperature_min": main.get("temp_min"),
        "temperature_max": main.get("temp_max"),
        "description": _weather_description(payload),
        "humidity_percent": main.get("humidity"),
        "wind_speed": wind.get("speed"),
        "wind_direction_degrees": wind.get("deg"),
        "precipitation_probability_percent": (
            round(float(payload["pop"]) * 100, 1)
            if isinstance(payload.get("pop"), (int, float))
            and not isinstance(payload.get("pop"), bool)
            else None
        ),
        "rain_mm": rain.get("1h", rain.get("3h")),
        "snow_mm": snow.get("1h", snow.get("3h")),
    }


@ToolRegistry.register(_TOOL_NAME)
class WeatherTool(BaseTool):
    """Fetch current or forecast weather for a dynamic location."""

    tool_id = _TOOL_NAME
    is_local = False

    def __init__(
        self,
        *,
        api_key: str | None = None,
        connector: WeatherConnector | None = None,
        config: Any = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._connector = connector or WeatherConnector()
        self._config_error = False
        if config is None:
            try:
                from openjarvis.core.config import load_config

                config = load_config().tools.weather
            except Exception:
                self._config_error = True
                config = None
        self._provider = str(getattr(config, "provider", "openweathermap") or "")
        self._default_location = str(
            getattr(config, "default_location", "") or ""
        ).strip()
        self._default_units = str(getattr(config, "units", "metric") or "").lower()
        self._default_language = str(getattr(config, "lang", "en") or "").lower()

    def _resolve_api_key(self) -> str | None:
        if self._api_key:
            return self._api_key
        try:
            key = get_tool_credential(_TOOL_NAME, _API_KEY_ENV)
        except (OSError, TypeError, ValueError):
            key = None
        if key and key.strip():
            return key.strip()
        return self._connector.stored_api_key()

    def is_configured(self) -> bool:
        """Return credential presence without exposing the credential value."""
        return self._resolve_api_key() is not None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=_TOOL_NAME,
            description=(
                "Get current weather and an optional forecast for a dynamic city, "
                "region, postal code, or 'city,country-code' location. Pass the "
                "location requested by the user; descriptions use the requested "
                "language."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "Location to look up, such as 'Vienna,AT', "
                            "'Sankt Johann in Tirol', or a postal code."
                        ),
                    },
                    "units": {
                        "type": "string",
                        "enum": sorted(_VALID_UNITS),
                        "description": (
                            "Unit system. Defaults to [tools.weather].units "
                            "(metric unless configured)."
                        ),
                    },
                    "language": {
                        "type": "string",
                        "description": (
                            "OpenWeatherMap language code such as 'en', 'de', "
                            "'fr', or 'pt_br'."
                        ),
                    },
                    "include_forecast": {
                        "type": "boolean",
                        "description": (
                            "Include 3-hour forecast intervals. Use for future, "
                            "rain, or tomorrow questions. Defaults to false."
                        ),
                    },
                    "forecast_hours": {
                        "type": "integer",
                        "minimum": _MIN_FORECAST_HOURS,
                        "maximum": _MAX_FORECAST_HOURS,
                        "description": (
                            "Forecast horizon in hours, from 3 to 120. Defaults to 24."
                        ),
                    },
                },
                "additionalProperties": False,
            },
            category="weather",
            latency_estimate=1.0,
            timeout_seconds=30.0,
            required_capabilities=["network:fetch"],
            metadata={
                "provider": "openweathermap",
                "requires_api_key": _API_KEY_ENV,
                "credentials_configured": self.is_configured(),
            },
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._config_error:
            return self._failure("Weather configuration could not be loaded.")
        if self._provider.lower() != "openweathermap":
            return self._failure(
                f"Unsupported weather provider '{self._provider}'. "
                "Only 'openweathermap' is supported."
            )

        location_value = params.get("location", self._default_location)
        if not isinstance(location_value, str):
            return self._failure("Location must be a string.")
        location = location_value.strip()
        if not location:
            return self._failure(
                "A weather location is required. Pass location or configure "
                "[tools.weather].default_location."
            )
        if len(location) > _MAX_LOCATION_LENGTH:
            return self._failure(
                f"Location must be at most {_MAX_LOCATION_LENGTH} characters."
            )
        if any(ord(char) < 32 or ord(char) == 127 for char in location):
            return self._failure("Location must not contain control characters.")

        units_value = params.get("units", self._default_units)
        if not isinstance(units_value, str):
            return self._failure("Units must be 'metric' or 'imperial'.")
        units = units_value.strip().lower()
        if units not in _VALID_UNITS:
            return self._failure("Units must be 'metric' or 'imperial'.")

        language_value = params.get("language", self._default_language)
        if not isinstance(language_value, str):
            return self._failure("Language must be an OpenWeatherMap language code.")
        language = language_value.strip().lower()
        if not _LANGUAGE_PATTERN.fullmatch(language):
            return self._failure(
                "Language must be a two-letter code with an optional region, "
                "such as 'de' or 'pt_br'."
            )

        include_forecast = params.get("include_forecast", False)
        if not isinstance(include_forecast, bool):
            return self._failure("include_forecast must be true or false.")
        forecast_hours = params.get("forecast_hours", 24)
        if isinstance(forecast_hours, bool) or not isinstance(forecast_hours, int):
            return self._failure("forecast_hours must be an integer from 3 to 120.")
        if not _MIN_FORECAST_HOURS <= forecast_hours <= _MAX_FORECAST_HOURS:
            return self._failure("forecast_hours must be between 3 and 120.")

        api_key = self._resolve_api_key()
        if not api_key:
            return self._failure(
                "No OpenWeatherMap API key configured. Connect the Weather "
                f"connector or set {_API_KEY_ENV}."
            )

        try:
            current_payload, forecast_payload = fetch_weather(
                api_key=api_key,
                location=location,
                units=units,
                language=language,
                include_forecast=include_forecast,
                forecast_count=math.ceil(forecast_hours / 3),
            )
        except WeatherAPIError as exc:
            return self._failure(f"Weather lookup failed: {exc}")
        except Exception:
            # Do not stringify unknown provider exceptions: request exceptions
            # can contain the URL query and therefore the API key.
            return self._failure("Weather lookup failed unexpectedly.")

        sys_payload = current_payload.get("sys")
        coord_payload = current_payload.get("coord")
        if not isinstance(sys_payload, dict):
            sys_payload = {}
        if not isinstance(coord_payload, dict):
            coord_payload = {}
        result: dict[str, Any] = {
            "provider": "openweathermap",
            "location": {
                "requested": location,
                "name": current_payload.get("name"),
                "country": sys_payload.get("country"),
                "latitude": coord_payload.get("lat"),
                "longitude": coord_payload.get("lon"),
            },
            "units": units,
            "language": language,
            "current": _structured_conditions(current_payload),
        }
        forecast_entries: list[dict[str, Any]] = []
        if forecast_payload is not None:
            raw_entries = forecast_payload.get("list")
            if isinstance(raw_entries, list):
                forecast_entries = [
                    _structured_conditions(entry)
                    for entry in raw_entries
                    if isinstance(entry, dict)
                ]
            result["forecast"] = forecast_entries

        return ToolResult(
            tool_name=_TOOL_NAME,
            content=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            success=True,
            metadata={
                "provider": "openweathermap",
                "location": location,
                "units": units,
                "language": language,
                "forecast_entries": len(forecast_entries),
            },
        )

    @staticmethod
    def _failure(message: str) -> ToolResult:
        return ToolResult(tool_name=_TOOL_NAME, content=message, success=False)


__all__ = ["WeatherTool"]
