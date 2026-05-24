"""Open-Meteo Forecast API client and Korean weather summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal

import httpx

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

SEOUL_LATITUDE = 37.566
SEOUL_LONGITUDE = 126.9784
SEOUL_TIMEZONE = "Asia/Seoul"

WeatherProfile = Literal["basic", "detail"]

BASIC_CURRENT = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "weather_code",
    "is_day",
    "wind_speed_10m",
]
BASIC_HOURLY = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation_probability",
    "precipitation",
    "rain",
    "weather_code",
    "relative_humidity_2m",
    "wind_speed_10m",
]
BASIC_DAILY = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "precipitation_probability_max",
    "precipitation_sum",
    "rain_sum",
    "wind_speed_10m_max",
    "uv_index_max",
    "sunrise",
    "sunset",
]

DETAIL_CURRENT = [
    "temperature_2m",
    "precipitation",
    "rain",
    "weather_code",
    "is_day",
    "apparent_temperature",
]
DETAIL_MINUTELY_15 = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation",
    "snowfall_height",
    "snowfall",
    "rain",
    "weather_code",
    "wind_gusts_10m",
    "lightning_potential",
    "is_day",
    "sunshine_duration",
    "freezing_level_height",
    "wind_speed_80m",
    "wind_direction_10m",
    "wind_direction_80m",
    "wind_speed_10m",
]
DETAIL_HOURLY = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation_probability",
    "precipitation",
    "rain",
    "showers",
    "snowfall",
    "snow_depth",
    "visibility",
    "cloud_cover_high",
    "cloud_cover_mid",
    "cloud_cover_low",
    "cloud_cover",
    "pressure_msl",
    "weather_code",
    "surface_pressure",
    "temperature_180m",
    "temperature_120m",
    "temperature_80m",
    "wind_gusts_10m",
    "wind_direction_180m",
    "wind_direction_120m",
    "wind_direction_80m",
    "wind_direction_10m",
    "wind_speed_180m",
    "wind_speed_120m",
    "wind_speed_80m",
    "wind_speed_10m",
]
DETAIL_DAILY = [
    "weather_code",
    "uv_index_max",
    "uv_index_clear_sky_max",
    "sunset",
    "sunrise",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "temperature_2m_min",
    "temperature_2m_max",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "precipitation_hours",
    "precipitation_sum",
    "snowfall_sum",
    "precipitation_probability_max",
    "rain_sum",
]

DETAIL_KEYWORDS = (
    "상세",
    "자세히",
    "디테일",
    "기압",
    "습도",
    "풍속",
    "자외선",
    "가시거리",
)


def _join(fields: list[str]) -> str:
    return ",".join(fields)


def build_open_meteo_params(
    *,
    profile: WeatherProfile = "basic",
    latitude: float = SEOUL_LATITUDE,
    longitude: float = SEOUL_LONGITUDE,
    timezone: str = SEOUL_TIMEZONE,
    detail_past_days: int = 7,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
    }
    if profile == "detail":
        params.update(
            {
                "current": _join(DETAIL_CURRENT),
                "minutely_15": _join(DETAIL_MINUTELY_15),
                "hourly": _join(DETAIL_HOURLY),
                "daily": _join(DETAIL_DAILY),
                "forecast_days": 16,
                "past_days": detail_past_days,
            }
        )
    else:
        params.update(
            {
                "current": _join(BASIC_CURRENT),
                "hourly": _join(BASIC_HOURLY),
                "daily": _join(BASIC_DAILY),
                "forecast_days": 7,
            }
        )
    return params


def infer_weather_profile(query: str, requested: str | None = None) -> WeatherProfile:
    if requested in {"basic", "detail"}:
        return requested
    return "detail" if any(word in query for word in DETAIL_KEYWORDS) else "basic"


@dataclass(slots=True)
class OpenMeteoWeatherClient:
    """Small keyless Open-Meteo Forecast API client."""

    url: str = OPEN_METEO_FORECAST_URL
    timeout: float = 15.0
    detail_past_days: int = 7

    def fetch_forecast(
        self,
        *,
        profile: WeatherProfile = "basic",
        latitude: float = SEOUL_LATITUDE,
        longitude: float = SEOUL_LONGITUDE,
        timezone: str = SEOUL_TIMEZONE,
    ) -> Dict[str, Any]:
        params = build_open_meteo_params(
            profile=profile,
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            detail_past_days=self.detail_past_days,
        )
        response = httpx.get(self.url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()


def format_weather_summary(
    data: Dict[str, Any],
    query: str = "",
    *,
    profile: WeatherProfile = "basic",
    location_name: str = "서울",
) -> str:
    """Return a Korean weather summary for common Friday weather queries."""
    intent = _infer_intent(query)
    if profile == "detail":
        return _format_detail_summary(data, location_name)
    if intent == "week":
        return _format_week_summary(data, location_name)
    return _format_day_summary(data, intent, location_name)


def _infer_intent(query: str) -> Literal["today", "tomorrow", "week", "detail"]:
    q = query.strip()
    if any(word in q for word in DETAIL_KEYWORDS):
        return "detail"
    if "내일" in q:
        return "tomorrow"
    if "이번 주" in q or "이번주" in q or "주간" in q or "7일" in q:
        return "week"
    return "today"


def _format_detail_summary(data: Dict[str, Any], location_name: str) -> str:
    current = data.get("current") or {}
    hourly = data.get("hourly") or {}
    daily = data.get("daily") or {}
    lines = [
        f"{location_name} 상세 날씨입니다.",
        (
            f"현재 {_weather_code_ko(current.get('weather_code'))}, "
            f"기온 {_num(current.get('temperature_2m'), '°C')}"
            f"(체감 {_num(current.get('apparent_temperature'), '°C')})입니다."
        ),
        (
            f"습도 {_num(_first(hourly, 'relative_humidity_2m'), '%')}, "
            f"기압 {_num(_first(hourly, 'pressure_msl'), 'hPa')}, "
            f"가시거리 {_num(_first(hourly, 'visibility'), 'm')}입니다."
        ),
        (
            f"풍속 {_num(_first(hourly, 'wind_speed_10m'), 'km/h')}, "
            f"돌풍 {_num(_first(hourly, 'wind_gusts_10m'), 'km/h')}, "
            f"자외선 지수 {_num(_first(daily, 'uv_index_max'))}입니다."
        ),
    ]
    return "\n".join(lines)


def _format_week_summary(data: Dict[str, Any], location_name: str) -> str:
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    codes = daily.get("weather_code") or []
    max_temps = daily.get("temperature_2m_max") or []
    min_temps = daily.get("temperature_2m_min") or []
    precip_probs = daily.get("precipitation_probability_max") or []
    precip_sums = daily.get("precipitation_sum") or []
    lines = [f"이번 주 {location_name} 날씨 요약입니다."]
    for i, date in enumerate(dates[:7]):
        lines.append(
            "- "
            f"{date}: {_weather_code_ko(_at(codes, i))}, "
            f"{_num(_at(min_temps, i), '°C')}~{_num(_at(max_temps, i), '°C')}, "
            f"강수확률 {_num(_at(precip_probs, i), '%')}, "
            f"강수량 {_num(_at(precip_sums, i), 'mm')}"
        )
    return "\n".join(lines)


def _format_day_summary(
    data: Dict[str, Any],
    intent: str,
    location_name: str,
) -> str:
    current = data.get("current") or {}
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    codes = daily.get("weather_code") or []
    max_temps = daily.get("temperature_2m_max") or []
    min_temps = daily.get("temperature_2m_min") or []
    precip_probs = daily.get("precipitation_probability_max") or []
    precip_sums = daily.get("precipitation_sum") or []
    rain_sums = daily.get("rain_sum") or []
    wind_max = daily.get("wind_speed_10m_max") or []
    uv_max = daily.get("uv_index_max") or []

    idx = 1 if intent == "tomorrow" else 0
    label = "내일" if intent == "tomorrow" else "오늘"
    if idx >= len(dates):
        idx = 0

    if intent == "today":
        header = (
            f"현재 {location_name}은 {_weather_code_ko(current.get('weather_code'))}, "
            f"기온 {_num(current.get('temperature_2m'), '°C')}"
            f"(체감 {_num(current.get('apparent_temperature'), '°C')})입니다."
        )
    else:
        header = (
            f"{label} {location_name} 날씨는 {_weather_code_ko(_at(codes, idx))}입니다."
        )

    rain_hint = "비 가능성이 낮습니다."
    precip_prob = _at(precip_probs, idx)
    rain_sum = _at(rain_sums, idx)
    precip_sum = _at(precip_sums, idx)
    if (precip_prob or 0) >= 50 or (rain_sum or 0) > 0 or (precip_sum or 0) > 0:
        rain_hint = (
            f"비 가능성이 있습니다. 강수확률 {_num(precip_prob, '%')}, "
            f"예상 강수량 {_num(precip_sum, 'mm')}입니다."
        )

    return (
        f"{header}\n"
        f"{label} 예상 기온은 {_num(_at(min_temps, idx), '°C')}~"
        f"{_num(_at(max_temps, idx), '°C')}, "
        f"최대 풍속은 {_num(_at(wind_max, idx), 'km/h')}, "
        f"자외선 지수는 {_num(_at(uv_max, idx))}입니다.\n"
        f"{rain_hint}"
    )


def _weather_code_ko(code: int | None) -> str:
    labels = {
        0: "맑음",
        1: "대체로 맑음",
        2: "부분적으로 흐림",
        3: "흐림",
        45: "안개",
        48: "서리 안개",
        51: "약한 이슬비",
        53: "이슬비",
        55: "강한 이슬비",
        61: "약한 비",
        63: "비",
        65: "강한 비",
        71: "약한 눈",
        73: "눈",
        75: "강한 눈",
        80: "약한 소나기",
        81: "소나기",
        82: "강한 소나기",
        95: "뇌우",
        96: "우박 동반 뇌우",
        99: "강한 우박 동반 뇌우",
    }
    return labels.get(code, f"날씨 코드 {code}" if code is not None else "정보 없음")


def _num(value: Any, suffix: str = "", default: str = "-") -> str:
    if value is None:
        return default
    if isinstance(value, float):
        text = f"{value:.1f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text}{suffix}"


def _first(data: Dict[str, Any], key: str) -> Any:
    values = data.get(key) or []
    return values[0] if values else None


def _at(values: list[Any], idx: int) -> Any:
    return values[idx] if 0 <= idx < len(values) else None


__all__ = [
    "OpenMeteoWeatherClient",
    "WeatherProfile",
    "build_open_meteo_params",
    "format_weather_summary",
    "infer_weather_profile",
]
