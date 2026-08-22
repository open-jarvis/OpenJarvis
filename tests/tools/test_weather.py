"""Tests for the native parameterized OpenWeatherMap tool."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest

from openjarvis.connectors.weather import WeatherAPIError, _weather_api_get
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolCall
from openjarvis.security.capabilities import DEFAULT_TOOL_CAPABILITIES
from openjarvis.tools._stubs import ToolExecutor
from openjarvis.tools.weather import WeatherTool


def _config(**overrides):
    values = {
        "provider": "openweathermap",
        "default_location": "",
        "units": "metric",
        "lang": "en",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _current_response():
    return {
        "dt": 1_800_000_000,
        "name": "Wien",
        "coord": {"lat": 48.2082, "lon": 16.3738},
        "sys": {"country": "AT"},
        "main": {
            "temp": 19.5,
            "feels_like": 19.0,
            "temp_min": 18.0,
            "temp_max": 21.0,
            "humidity": 61,
        },
        "weather": [{"description": "leichter Regen"}],
        "wind": {"speed": 3.4, "deg": 250},
        "rain": {"1h": 0.4},
    }


def _forecast_response():
    return {
        "list": [
            {
                "dt_txt": "2027-01-15 12:00:00",
                "main": {"temp": 20.0, "humidity": 59},
                "weather": [{"description": "bewölkt"}],
                "wind": {"speed": 3.0},
                "pop": 0.375,
                "rain": {"3h": 1.2},
            }
        ]
    }


def test_registered_and_declared_external():
    import openjarvis.tools.weather as weather_module

    weather_module = importlib.reload(weather_module)
    assert ToolRegistry.contains("get_weather")
    tool_cls = ToolRegistry.get("get_weather")
    assert tool_cls is weather_module.WeatherTool
    tool = tool_cls(api_key="test-key", config=_config())
    assert tool.is_local is False
    assert tool.spec.required_capabilities == ["network:fetch"]
    assert DEFAULT_TOOL_CAPABILITIES["get_weather"] == ["network:fetch"]
    assert tool.spec.parameters["properties"]["location"]["type"] == "string"
    assert tool.spec.metadata["credentials_configured"] is True


@pytest.mark.parametrize("agent_type", ["simple", "native_react", "orchestrator"])
def test_managed_agent_resolver_instantiates_native_weather_tool(agent_type):
    from openjarvis.agents.tool_resolver import resolve_agent_tools

    ToolRegistry.register_value("get_weather", WeatherTool)
    resolved = resolve_agent_tools(
        {"agent_type": agent_type, "config": {"tools": ["get_weather"]}},
        engine=None,
        model="test-model",
    )
    try:
        assert set(resolved.by_name) == {"get_weather"}
        assert resolved.openai_specs[0]["function"]["name"] == "get_weather"
    finally:
        resolved.close()


def test_tool_executor_applies_external_boundary_guard():
    guard = Mock()
    guard.check_outbound.side_effect = lambda call: call
    tool = WeatherTool(api_key="test-key", config=_config())
    executor = ToolExecutor([tool], boundary_guard=guard)
    call = ToolCall(
        id="weather-1",
        name="get_weather",
        arguments='{"location":"Vienna,AT"}',
    )
    with patch(
        "openjarvis.tools.weather.fetch_weather",
        return_value=(_current_response(), None),
    ):
        result = executor.execute(call)

    assert result.success is True
    guard.check_outbound.assert_called_once_with(call)


def test_dynamic_location_units_language_and_structured_current():
    tool = WeatherTool(api_key="secret-key", config=_config())
    with patch(
        "openjarvis.tools.weather.fetch_weather",
        return_value=(_current_response(), None),
    ) as fetch:
        result = tool.execute(location=" Vienna,AT ", units="metric", language="de")

    assert result.success is True
    fetch.assert_called_once_with(
        api_key="secret-key",
        location="Vienna,AT",
        units="metric",
        language="de",
        include_forecast=False,
        forecast_count=8,
    )
    payload = json.loads(result.content)
    assert payload["location"] == {
        "requested": "Vienna,AT",
        "name": "Wien",
        "country": "AT",
        "latitude": 48.2082,
        "longitude": 16.3738,
    }
    assert payload["current"]["temperature"] == 19.5
    assert payload["current"]["description"] == "leichter Regen"
    assert payload["current"]["humidity_percent"] == 61
    assert payload["current"]["wind_speed"] == 3.4
    assert "secret-key" not in result.content
    assert "secret-key" not in str(result.metadata)


def test_forecast_is_bounded_and_structured():
    tool = WeatherTool(api_key="test-key", config=_config())
    with patch(
        "openjarvis.tools.weather.fetch_weather",
        return_value=(_current_response(), _forecast_response()),
    ) as fetch:
        result = tool.execute(
            location="Innsbruck,AT",
            include_forecast=True,
            forecast_hours=25,
        )

    assert result.success is True
    assert fetch.call_args.kwargs["forecast_count"] == 9
    forecast = json.loads(result.content)["forecast"]
    assert forecast[0]["time"] == "2027-01-15 12:00:00"
    assert forecast[0]["precipitation_probability_percent"] == 37.5
    assert forecast[0]["rain_mm"] == 1.2
    assert result.metadata["forecast_entries"] == 1


def test_config_defaults_are_used_when_arguments_are_omitted():
    tool = WeatherTool(
        api_key="test-key",
        config=_config(
            default_location="Sankt Johann in Tirol",
            units="imperial",
            lang="de",
        ),
    )
    with patch(
        "openjarvis.tools.weather.fetch_weather",
        return_value=(_current_response(), None),
    ) as fetch:
        result = tool.execute()

    assert result.success is True
    assert fetch.call_args.kwargs["location"] == "Sankt Johann in Tirol"
    assert fetch.call_args.kwargs["units"] == "imperial"
    assert fetch.call_args.kwargs["language"] == "de"


def test_secure_tool_credential_precedes_connector(monkeypatch):
    connector = Mock()
    connector.stored_api_key.return_value = "connector-key"
    tool = WeatherTool(connector=connector, config=_config())
    monkeypatch.setattr(
        "openjarvis.tools.weather.get_tool_credential",
        lambda *_args, **_kwargs: "credential-key",
    )
    with patch(
        "openjarvis.tools.weather.fetch_weather",
        return_value=(_current_response(), None),
    ) as fetch:
        result = tool.execute(location="Paris,FR")

    assert result.success is True
    assert fetch.call_args.kwargs["api_key"] == "credential-key"
    connector.stored_api_key.assert_not_called()


def test_existing_connector_credential_is_reused(monkeypatch):
    connector = Mock()
    connector.stored_api_key.return_value = "connector-key"
    tool = WeatherTool(connector=connector, config=_config())
    monkeypatch.setattr(
        "openjarvis.tools.weather.get_tool_credential",
        lambda *_args, **_kwargs: None,
    )
    with patch(
        "openjarvis.tools.weather.fetch_weather",
        return_value=(_current_response(), None),
    ) as fetch:
        result = tool.execute(location="Boston,US")

    assert result.success is True
    assert fetch.call_args.kwargs["api_key"] == "connector-key"


def test_default_connector_path_honors_runtime_openjarvis_home(tmp_path, monkeypatch):
    from openjarvis.connectors.weather import WeatherConnector

    root = tmp_path / "relocated-home"
    credential_path = root / "connectors" / "weather.json"
    credential_path.parent.mkdir(parents=True)
    credential_path.write_text(
        '{"api_key":"relocated-connector-key","location":"Vienna"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENJARVIS_HOME", str(root))
    monkeypatch.setattr(
        "openjarvis.tools.weather.get_tool_credential",
        lambda *_args, **_kwargs: None,
    )
    tool = WeatherTool(connector=WeatherConnector(), config=_config())

    assert tool.is_configured() is True
    with patch(
        "openjarvis.tools.weather.fetch_weather",
        return_value=(_current_response(), None),
    ) as fetch:
        result = tool.execute(location="Vienna")

    assert result.success is True
    assert fetch.call_args.kwargs["api_key"] == "relocated-connector-key"


def test_missing_credentials_fails_without_calling_provider(monkeypatch):
    connector = Mock()
    connector.stored_api_key.return_value = None
    tool = WeatherTool(connector=connector, config=_config())
    monkeypatch.setattr(
        "openjarvis.tools.weather.get_tool_credential",
        lambda *_args, **_kwargs: None,
    )
    with patch("openjarvis.tools.weather.fetch_weather") as fetch:
        result = tool.execute(location="Vienna")

    assert result.success is False
    assert "OPENWEATHERMAP_API_KEY" in result.content
    fetch.assert_not_called()


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, "location is required"),
        ({"location": 123}, "must be a string"),
        ({"location": "x" * 201}, "at most 200"),
        ({"location": "Vienna\nappid=stolen"}, "control characters"),
        ({"location": "Vienna", "units": "kelvin"}, "metric"),
        ({"location": "Vienna", "language": "../../de"}, "two-letter"),
        ({"location": "Vienna", "include_forecast": "yes"}, "true or false"),
        ({"location": "Vienna", "forecast_hours": True}, "integer"),
        ({"location": "Vienna", "forecast_hours": 121}, "between 3 and 120"),
    ],
)
def test_invalid_arguments_fail_before_network(params, expected):
    tool = WeatherTool(api_key="test-key", config=_config())
    with patch("openjarvis.tools.weather.fetch_weather") as fetch:
        result = tool.execute(**params)

    assert result.success is False
    assert expected in result.content
    fetch.assert_not_called()


def test_provider_error_never_exposes_api_key():
    secret = "super-secret-weather-key"
    tool = WeatherTool(api_key=secret, config=_config())
    with patch(
        "openjarvis.tools.weather.fetch_weather",
        side_effect=httpx.RequestError(
            f"request failed: https://example.test/?appid={secret}"
        ),
    ):
        result = tool.execute(location="Vienna")

    assert result.success is False
    assert secret not in result.content
    assert "unexpectedly" in result.content


def test_http_status_error_is_credential_safe():
    secret = "status-secret-key"
    request = httpx.Request(
        "GET", f"https://api.openweathermap.org/weather?appid={secret}"
    )
    response = httpx.Response(
        401,
        request=request,
        json={"cod": 401, "message": "Invalid API key"},
    )
    with patch("openjarvis.connectors.weather.httpx.get", return_value=response):
        with pytest.raises(WeatherAPIError) as exc_info:
            _weather_api_get(
                "https://api.openweathermap.org/weather",
                {"appid": secret},
            )

    message = str(exc_info.value)
    assert message == "OpenWeatherMap returned HTTP 401: authentication failed"
    assert secret not in message


def test_http_status_provider_message_cannot_echo_credential():
    secret = "echoed-secret-key"
    request = httpx.Request(
        "GET", f"https://api.openweathermap.org/weather?appid={secret}"
    )
    response = httpx.Response(
        400,
        request=request,
        json={"message": f"bad appid {secret}"},
    )
    with patch("openjarvis.connectors.weather.httpx.get", return_value=response):
        with pytest.raises(WeatherAPIError) as exc_info:
            _weather_api_get(
                "https://api.openweathermap.org/weather",
                {"appid": secret},
            )

    assert secret not in str(exc_info.value)
    assert str(exc_info.value) == (
        "OpenWeatherMap returned HTTP 400: the request was invalid"
    )


def test_request_error_is_credential_safe():
    secret = "request-secret-key"
    request = httpx.Request(
        "GET", f"https://api.openweathermap.org/weather?appid={secret}"
    )
    with patch(
        "openjarvis.connectors.weather.httpx.get",
        side_effect=httpx.ConnectError("connection failed", request=request),
    ):
        with pytest.raises(WeatherAPIError) as exc_info:
            _weather_api_get(
                "https://api.openweathermap.org/weather",
                {"appid": secret},
            )

    assert str(exc_info.value) == "OpenWeatherMap could not be reached"
    assert secret not in str(exc_info.value)
