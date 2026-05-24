"""Weather tool wrapper for the keyless Open-Meteo provider."""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.weather.open_meteo import (
    SEOUL_LATITUDE,
    SEOUL_LONGITUDE,
    SEOUL_TIMEZONE,
    OpenMeteoWeatherClient,
    WeatherProfile,
    format_weather_summary,
    infer_weather_profile,
)


class _BaseOpenMeteoWeatherTool(BaseTool):
    """Shared Open-Meteo weather tool implementation."""

    tool_id = "weather"
    profile_override: WeatherProfile | None = None
    description_profile = (
        "Uses a small basic profile for normal chat and a detail profile for "
        "explicit detailed weather requests."
    )
    is_local = False

    def __init__(
        self,
        client: OpenMeteoWeatherClient | None = None,
        *,
        default_profile: WeatherProfile | None = None,
    ) -> None:
        self._default_profile = default_profile
        latitude = SEOUL_LATITUDE
        longitude = SEOUL_LONGITUDE
        timezone = SEOUL_TIMEZONE
        history_days = 92
        detail_past_days = 7
        try:
            from openjarvis.core.config import load_config

            weather_cfg = load_config().tools.weather
            latitude = weather_cfg.latitude
            longitude = weather_cfg.longitude
            timezone = weather_cfg.timezone
            history_days = weather_cfg.history_days
            detail_past_days = weather_cfg.detail_past_days
            self._default_profile = self._default_profile or weather_cfg.default_profile
        except Exception:
            pass

        self._latitude = latitude
        self._longitude = longitude
        self._timezone = timezone
        self._history_days = history_days
        self._client = client or OpenMeteoWeatherClient(
            detail_past_days=detail_past_days
        )

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Get current weather and forecasts from Open-Meteo. No API key "
                f"is required. {self.description_profile}"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "User weather question, e.g. 오늘 날씨 알려줘, "
                            "상세 날씨 알려줘, 내일 비 와?, 이번 주 날씨 알려줘."
                        ),
                    },
                    "profile": {
                        "type": "string",
                        "enum": ["basic", "detail"],
                        "description": "Optional weather profile override.",
                    },
                    "latitude": {
                        "type": "number",
                        "description": "Latitude. Defaults to Seoul.",
                    },
                    "longitude": {
                        "type": "number",
                        "description": "Longitude. Defaults to Seoul.",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone. Defaults to Asia/Seoul.",
                    },
                    "location_name": {
                        "type": "string",
                        "description": "Display name for Korean summaries.",
                    },
                },
                "required": [],
            },
            category="weather",
            metadata={
                "provider": "open-meteo",
                "requires_api_key": False,
                "history_days_available": self._history_days,
            },
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query") or "오늘 날씨 알려줘")
        if self.profile_override is not None:
            profile = self.profile_override
        else:
            profile = infer_weather_profile(
                query,
                requested=str(params.get("profile")) if params.get("profile") else None,
            )
            if self._default_profile == "detail" and "profile" not in params:
                profile = infer_weather_profile(query, requested=self._default_profile)

        latitude = float(
            params.get("latitude", getattr(self, "_latitude", SEOUL_LATITUDE))
        )
        longitude = float(
            params.get("longitude", getattr(self, "_longitude", SEOUL_LONGITUDE))
        )
        timezone = str(
            params.get("timezone", getattr(self, "_timezone", SEOUL_TIMEZONE))
        )
        location_name = str(params.get("location_name") or "서울")

        try:
            data = self._client.fetch_forecast(
                profile=profile,
                latitude=latitude,
                longitude=longitude,
                timezone=timezone,
            )
            return ToolResult(
                tool_name=self.tool_id,
                content=format_weather_summary(
                    data,
                    query,
                    profile=profile,
                    location_name=location_name,
                ),
                success=True,
                metadata={
                    "provider": "open-meteo",
                    "profile": profile,
                    "latitude": latitude,
                    "longitude": longitude,
                    "timezone": timezone,
                    "location_name": location_name,
                    "raw": data,
                },
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"날씨 정보를 가져오지 못했습니다: {exc}",
                success=False,
                metadata={"provider": "open-meteo", "profile": profile},
            )


@ToolRegistry.register("weather")
class WeatherTool(_BaseOpenMeteoWeatherTool):
    """Fetch current weather and forecasts from Open-Meteo."""

    tool_id = "weather"


@ToolRegistry.register("weather_basic")
class WeatherBasicTool(_BaseOpenMeteoWeatherTool):
    """Fetch a lightweight Open-Meteo forecast for everyday weather questions."""

    tool_id = "weather_basic"
    profile_override = "basic"
    description_profile = (
        "Always uses the lightweight basic profile for everyday Korean questions "
        "like 오늘 날씨 알려줘, 내일 비 와?, and 이번 주 날씨 알려줘."
    )


@ToolRegistry.register("weather_detail")
class WeatherDetailTool(_BaseOpenMeteoWeatherTool):
    """Fetch a detailed Open-Meteo forecast for weather diagnostics."""

    tool_id = "weather_detail"
    profile_override = "detail"
    description_profile = (
        "Always uses the detail profile for detailed requests mentioning 상세, "
        "자세히, 디테일, 습도, 기압, 풍속, 자외선, or 가시거리."
    )


__all__ = ["WeatherBasicTool", "WeatherDetailTool", "WeatherTool"]
