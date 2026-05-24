"""Tests for the local-first Open-Meteo weather tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openjarvis.core.config import EngineConfig
from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.weather import WeatherBasicTool, WeatherDetailTool, WeatherTool
from openjarvis.weather.open_meteo import (
    SEOUL_LATITUDE,
    SEOUL_LONGITUDE,
    SEOUL_TIMEZONE,
    OpenMeteoWeatherClient,
    build_open_meteo_params,
    format_weather_summary,
    infer_weather_profile,
)

_OPEN_METEO_RESPONSE = {
    "current": {
        "time": "2026-05-25T09:00",
        "temperature_2m": 20.4,
        "apparent_temperature": 20.0,
        "precipitation": 0.0,
        "rain": 0.0,
        "weather_code": 1,
        "is_day": 1,
        "wind_speed_10m": 8.5,
    },
    "hourly": {
        "time": ["2026-05-25T09:00"],
        "relative_humidity_2m": [58],
        "pressure_msl": [1013.2],
        "visibility": [12000],
        "wind_speed_10m": [8.5],
        "wind_gusts_10m": [15.0],
    },
    "daily": {
        "time": [
            "2026-05-25",
            "2026-05-26",
            "2026-05-27",
            "2026-05-28",
            "2026-05-29",
            "2026-05-30",
            "2026-05-31",
        ],
        "weather_code": [1, 61, 3, 0, 2, 63, 1],
        "temperature_2m_max": [25.0, 22.0, 24.0, 26.0, 25.0, 21.0, 24.0],
        "temperature_2m_min": [16.0, 15.0, 17.0, 18.0, 17.0, 14.0, 16.0],
        "apparent_temperature_max": [25.2, 21.8, 24.1, 26.4, 25.3, 20.8, 24.2],
        "apparent_temperature_min": [16.1, 15.2, 17.1, 18.1, 17.2, 14.2, 16.1],
        "precipitation_probability_max": [10, 80, 20, 0, 30, 90, 10],
        "precipitation_sum": [0.0, 4.2, 0.0, 0.0, 0.0, 12.0, 0.0],
        "rain_sum": [0.0, 4.2, 0.0, 0.0, 0.0, 12.0, 0.0],
        "wind_speed_10m_max": [12.0, 18.0, 14.0, 9.0, 12.0, 20.0, 10.0],
        "uv_index_max": [6.0, 3.0, 5.0, 7.0, 6.0, 2.0, 6.0],
        "sunrise": [
            "2026-05-25T05:15",
            "2026-05-26T05:14",
            "2026-05-27T05:14",
            "2026-05-28T05:13",
            "2026-05-29T05:13",
            "2026-05-30T05:12",
            "2026-05-31T05:12",
        ],
        "sunset": [
            "2026-05-25T19:42",
            "2026-05-26T19:43",
            "2026-05-27T19:44",
            "2026-05-28T19:44",
            "2026-05-29T19:45",
            "2026-05-30T19:46",
            "2026-05-31T19:46",
        ],
    },
}


def test_weather_tool_registered():
    ToolRegistry.register_value("weather", WeatherTool)
    assert ToolRegistry.contains("weather")
    assert ToolRegistry.get("weather").tool_id == "weather"


def test_weather_profile_tools_registered():
    ToolRegistry.register_value("weather_basic", WeatherBasicTool)
    ToolRegistry.register_value("weather_detail", WeatherDetailTool)

    assert ToolRegistry.contains("weather_basic")
    assert ToolRegistry.contains("weather_detail")
    assert ToolRegistry.get("weather_basic").tool_id == "weather_basic"
    assert ToolRegistry.get("weather_detail").tool_id == "weather_detail"


def test_basic_profile_does_not_include_heavy_minutely_15_data():
    params = build_open_meteo_params()
    assert params["latitude"] == SEOUL_LATITUDE
    assert params["longitude"] == SEOUL_LONGITUDE
    assert params["timezone"] == SEOUL_TIMEZONE
    assert params["forecast_days"] == 7
    assert "minutely_15" not in params
    assert "past_days" not in params
    assert params["current"] == (
        "temperature_2m,apparent_temperature,precipitation,rain,"
        "weather_code,is_day,wind_speed_10m"
    )


def test_detail_profile_includes_minutely_expanded_hourly_and_16_days():
    params = build_open_meteo_params(profile="detail")
    assert params["forecast_days"] == 16
    assert params["past_days"] == 7
    assert "relative_humidity_2m" in params["minutely_15"]
    assert "lightning_potential" in params["minutely_15"]
    assert "pressure_msl" in params["hourly"]
    assert "visibility" in params["hourly"]
    assert "temperature_180m" in params["hourly"]
    assert "uv_index_clear_sky_max" in params["daily"]


def test_open_meteo_client_uses_keyless_params():
    response = MagicMock()
    response.json.return_value = _OPEN_METEO_RESPONSE
    response.raise_for_status.return_value = None

    with patch("openjarvis.weather.open_meteo.httpx.get", return_value=response) as get:
        data = OpenMeteoWeatherClient().fetch_forecast()

    assert data is _OPEN_METEO_RESPONSE
    _, kwargs = get.call_args
    assert "api_key" not in kwargs["params"]
    assert "apikey" not in kwargs["params"]
    assert kwargs["params"]["timezone"] == SEOUL_TIMEZONE


def test_infer_detail_profile_for_detailed_terms():
    assert infer_weather_profile("상세 날씨 알려줘") == "detail"
    assert infer_weather_profile("습도랑 기압 자세히 알려줘") == "detail"
    assert infer_weather_profile("오늘 날씨 알려줘") == "basic"


def test_cloud_fallback_setting_is_not_changed():
    assert EngineConfig().allow_cloud_fallback is False


def test_today_korean_summary():
    summary = format_weather_summary(_OPEN_METEO_RESPONSE, "오늘 날씨 알려줘")
    assert "현재 서울" in summary
    assert "대체로 맑음" in summary
    assert "20.4°C" in summary
    assert "비 가능성이 낮습니다" in summary


def test_detail_korean_summary():
    summary = format_weather_summary(
        _OPEN_METEO_RESPONSE, "상세 날씨 알려줘", profile="detail"
    )
    assert "서울 상세 날씨" in summary
    assert "습도 58%" in summary
    assert "기압 1013.2hPa" in summary
    assert "가시거리 12000m" in summary


def test_tomorrow_rain_korean_summary():
    summary = format_weather_summary(_OPEN_METEO_RESPONSE, "내일 비 와?")
    assert "내일 서울 날씨" in summary
    assert "약한 비" in summary
    assert "비 가능성이 있습니다" in summary
    assert "강수확률 80%" in summary


def test_week_korean_summary():
    summary = format_weather_summary(_OPEN_METEO_RESPONSE, "이번 주 날씨 알려줘")
    assert "이번 주 서울 날씨 요약" in summary
    assert summary.count("\n- ") == 7
    assert "2026-05-31" in summary


def test_weather_tool_execute_uses_basic_for_normal_chat():
    client = MagicMock()
    client.fetch_forecast.return_value = _OPEN_METEO_RESPONSE

    result = WeatherTool(client=client).execute(query="오늘 날씨 알려줘")

    assert result.success is True
    assert result.metadata["profile"] == "basic"
    client.fetch_forecast.assert_called_once_with(
        profile="basic",
        latitude=SEOUL_LATITUDE,
        longitude=SEOUL_LONGITUDE,
        timezone=SEOUL_TIMEZONE,
    )


def test_weather_tool_execute_uses_detail_for_detail_query():
    client = MagicMock()
    client.fetch_forecast.return_value = _OPEN_METEO_RESPONSE

    result = WeatherTool(client=client).execute(query="기압이랑 습도 자세히 알려줘")

    assert result.success is True
    assert result.metadata["profile"] == "detail"
    assert "서울 상세 날씨" in result.content
    client.fetch_forecast.assert_called_once_with(
        profile="detail",
        latitude=SEOUL_LATITUDE,
        longitude=SEOUL_LONGITUDE,
        timezone=SEOUL_TIMEZONE,
    )


def test_weather_basic_tool_always_uses_basic_profile():
    client = MagicMock()
    client.fetch_forecast.return_value = _OPEN_METEO_RESPONSE

    result = WeatherBasicTool(client=client).execute(query="습도랑 기압 자세히 알려줘")

    assert result.success is True
    assert result.tool_name == "weather_basic"
    assert result.metadata["profile"] == "basic"
    assert "오늘 서울 날씨" in result.content
    assert "서울 상세 날씨" not in result.content
    client.fetch_forecast.assert_called_once_with(
        profile="basic",
        latitude=SEOUL_LATITUDE,
        longitude=SEOUL_LONGITUDE,
        timezone=SEOUL_TIMEZONE,
    )


def test_weather_detail_tool_always_uses_detail_profile():
    client = MagicMock()
    client.fetch_forecast.return_value = _OPEN_METEO_RESPONSE

    result = WeatherDetailTool(client=client).execute(query="오늘 날씨 알려줘")

    assert result.success is True
    assert result.tool_name == "weather_detail"
    assert result.metadata["profile"] == "detail"
    assert "서울 상세 날씨" in result.content
    client.fetch_forecast.assert_called_once_with(
        profile="detail",
        latitude=SEOUL_LATITUDE,
        longitude=SEOUL_LONGITUDE,
        timezone=SEOUL_TIMEZONE,
    )


def test_weather_profile_tool_specs_use_specific_names():
    basic = WeatherBasicTool(client=MagicMock()).spec
    detail = WeatherDetailTool(client=MagicMock()).spec

    assert basic.name == "weather_basic"
    assert detail.name == "weather_detail"
    assert basic.metadata["provider"] == "open-meteo"
    assert detail.metadata["requires_api_key"] is False


def test_default_basic_profile_does_not_override_detail_query():
    client = MagicMock()
    client.fetch_forecast.return_value = _OPEN_METEO_RESPONSE

    result = WeatherTool(client=client, default_profile="basic").execute(
        query="상세 날씨 알려줘"
    )

    assert result.success is True
    assert result.metadata["profile"] == "detail"


def test_spec_works_with_injected_client():
    tool = WeatherTool(client=MagicMock())
    assert tool.spec.metadata["history_days_available"] == 92
