"""Tests for the native FXMacroData macro and FX data tool."""

from __future__ import annotations

import importlib
import json
from unittest.mock import patch

import httpx
import pytest

from openjarvis.core.credentials import get_required_credentials, is_credential_optional
from openjarvis.core.registry import ToolRegistry
from openjarvis.security.capabilities import DEFAULT_TOOL_CAPABILITIES
from openjarvis.tools.fx_macro import FXMacroDataTool

_KEY = "fxmd-secret-key-123456"
_GET = "openjarvis.tools.fx_macro.httpx.get"


def _response(status=200, body=None, *, text=None, headers=None):
    request = httpx.Request("GET", "https://api.fxmacrodata.com/v1/x")
    if text is not None:
        return httpx.Response(status, text=text, headers=headers, request=request)
    return httpx.Response(status, json=body, headers=headers, request=request)


def _history_payload(**extra):
    payload = {
        "name": "Inflation (CPI)",
        "source": "BLS",
        "pagination": {"has_more": False, "total_count": 1},
        "freemium_window": {
            "applied": True,
            "message": "Anonymous access returns the most recent 90 days.",
        },
        "freemium_delay": {
            "applied": True,
            "message": "Free access is delayed by 15 minutes.",
        },
        "data": [
            {
                "date": "2026-08-31",
                "val": 3.4,
                "previous_value": 3.4,
                "announcement_datetime": 1789129800,
                "announcement_datetime_local": "2026-09-11T08:30:00-04:00",
                "source_url": "https://www.bls.gov/",
            }
        ],
    }
    payload.update(extra)
    return payload


@pytest.fixture(autouse=True)
def _no_ambient_key(monkeypatch):
    monkeypatch.delenv("FXMACRODATA_API_KEY", raising=False)
    monkeypatch.setattr(
        "openjarvis.tools.fx_macro.get_tool_credential", lambda *a, **k: None
    )


def _run(tool=None, **params):
    tool = tool or FXMacroDataTool()
    return tool.execute(**params)


def test_registered_with_network_capability_and_optional_key():
    import openjarvis.tools.fx_macro as module

    module = importlib.reload(module)
    assert ToolRegistry.get("fx_macro_data") is module.FXMacroDataTool
    tool = module.FXMacroDataTool()
    assert tool.is_local is False
    assert tool.spec.required_capabilities == ["network:fetch"]
    assert DEFAULT_TOOL_CAPABILITIES["fx_macro_data"] == ["network:fetch"]
    assert tool.spec.metadata["credentials_configured"] is False
    assert is_credential_optional("fx_macro_data", "FXMACRODATA_API_KEY")
    assert get_required_credentials("fx_macro_data") == []


def test_keyless_history_sends_no_key_refuses_redirects_and_keeps_notices():
    with patch(_GET, return_value=_response(body=_history_payload())) as get:
        result = _run(
            action="indicator_history",
            currency=" usd ",
            indicator="Inflation",
            start_date="2026-07-01",
            end_date="2026-09-30",
            limit=5,
        )
    assert result.success, result.content
    args, kwargs = get.call_args
    assert args[0] == "https://api.fxmacrodata.com/v1/announcements/usd/inflation"
    assert "X-API-Key" not in kwargs["headers"]
    assert kwargs["follow_redirects"] is False
    assert kwargs["params"] == {
        "start_date": "2026-07-01",
        "end_date": "2026-09-30",
        "limit": "5",
    }
    data = json.loads(result.content)
    assert data["releases"][0]["value"] == 3.4
    assert data["releases"][0]["period"] == "2026-08-31"
    assert data["pagination"] == {"has_more": False, "total_count": 1}
    assert len(data["notices"]) == 2


def test_key_from_credentials_is_sent_as_header_and_never_returned(monkeypatch):
    monkeypatch.setattr(
        "openjarvis.tools.fx_macro.get_tool_credential", lambda *a, **k: f" {_KEY} "
    )
    body = _history_payload()
    body["data"][0]["source_url"] = f"https://example.test/?k={_KEY}"
    with patch(_GET, return_value=_response(body=body)) as get:
        result = _run(
            action="indicator_history", currency="EUR", indicator="policy_rate"
        )
    assert get.call_args.kwargs["headers"]["X-API-Key"] == _KEY
    assert result.success
    assert _KEY not in result.content
    assert "[REDACTED]" in result.content
    assert FXMacroDataTool().spec.metadata["credentials_configured"] is True


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_is_an_error(status):
    response = _response(status, text="", headers={"location": "http://evil.test/"})
    with patch(_GET, return_value=response):
        result = _run(
            FXMacroDataTool(api_key=_KEY), action="release_calendar", currency="USD"
        )
    assert not result.success
    assert "redirect" in result.content
    assert _KEY not in result.content


@pytest.mark.parametrize("status", [401, 403, 404, 422, 429, 500])
def test_http_errors_are_clean_and_do_not_echo_the_body(status):
    response = _response(status, body={"detail": f"bad key {_KEY}"})
    with patch(_GET, return_value=response):
        result = _run(
            FXMacroDataTool(api_key=_KEY), action="fx_rates", base="EUR", quote="USD"
        )
    assert not result.success
    assert f"HTTP {status}" in result.content
    assert _KEY not in result.content


def test_transport_error_text_is_never_interpolated():
    error = httpx.ConnectError(f"failed for X-API-Key={_KEY}")
    with patch(_GET, side_effect=error):
        result = _run(
            FXMacroDataTool(api_key=_KEY), action="indicator_catalogue", currency="USD"
        )
    assert not result.success
    assert (
        result.content == "FXMacroData lookup failed: FXMacroData could not be reached"
    )


def test_timeout_is_reported_as_such():
    with patch(_GET, side_effect=httpx.ReadTimeout(f"slow {_KEY}")):
        result = _run(action="indicator_catalogue", currency="USD")
    assert result.content == (
        "FXMacroData lookup failed: FXMacroData did not answer in time"
    )


def test_unexpected_exception_is_generic():
    with patch(_GET, side_effect=RuntimeError(_KEY)):
        result = _run(action="indicator_catalogue", currency="USD")
    assert result.content == "FXMacroData lookup failed unexpectedly."


@pytest.mark.parametrize(
    "response",
    [
        _response(text="<html>oops</html>"),
        _response(body=[1, 2]),
        _response(body={"detail": "This endpoint requires an API key"}),
        _response(body={"data": {"not": "a list"}}),
        _response(body=_history_payload(pagination=[])),
        _response(body=_history_payload(pagination={"has_more": "no"})),
    ],
)
def test_bad_200_bodies_are_errors(response):
    with patch(_GET, return_value=response):
        result = _run(action="indicator_history", currency="USD", indicator="inflation")
    assert not result.success
    assert result.content.startswith("FXMacroData lookup failed:")


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"action": "nope"}, "action must be one of"),
        (
            {"action": "indicator_history", "currency": "US", "indicator": "cpi"},
            "three-letter",
        ),
        (
            {"action": "indicator_history", "currency": "USD", "indicator": "c p i"},
            "indicator slug",
        ),
        ({"action": "indicator_history", "currency": "USD"}, "indicator slug"),
        (
            {
                "action": "indicator_history",
                "currency": "USD",
                "indicator": "cpi",
                "start_date": "2026/01/01",
            },
            "YYYY-MM-DD",
        ),
        (
            {
                "action": "indicator_history",
                "currency": "USD",
                "indicator": "cpi",
                "start_date": "2026-02-30",
            },
            "real calendar date",
        ),
        (
            {
                "action": "indicator_history",
                "currency": "USD",
                "indicator": "cpi",
                "start_date": "2026-05-01",
                "end_date": "2026-04-01",
            },
            "on or before",
        ),
        (
            {
                "action": "indicator_history",
                "currency": "USD",
                "indicator": "cpi",
                "limit": 101,
            },
            "between 1 and 100",
        ),
        (
            {
                "action": "indicator_history",
                "currency": "USD",
                "indicator": "cpi",
                "limit": True,
            },
            "integer",
        ),
        ({"action": "fx_rates", "base": "EUR"}, "quote must be"),
    ],
)
def test_invalid_input_never_calls_the_api(params, message):
    with patch(_GET) as get:
        result = _run(**params)
    assert not result.success
    assert message in result.content
    get.assert_not_called()


def test_calendar_filters_and_truncates_to_limit():
    rows = [
        {
            "release": f"r{i}",
            "name": "Payrolls",
            "announcement_datetime_utc": "2026-10-09T12:30:00+00:00",
            "date": "2026-09-30",
            "event_importance": "high",
        }
        for i in range(5)
    ]
    with patch(_GET, return_value=_response(body={"data": rows})) as get:
        result = _run(
            action="release_calendar",
            currency="USD",
            indicator="non_farm_payrolls",
            limit=2,
        )
    assert get.call_args.kwargs["params"] == {"indicator": "non_farm_payrolls"}
    events = json.loads(result.content)["events"]
    assert [e["release"] for e in events] == ["r0", "r1"]
    assert events[0]["reference_period"] == "2026-09-30"


def test_catalogue_is_summarised_and_empty_is_an_error():
    body = {
        "inflation": {
            "name": "Inflation (CPI)",
            "unit": "%",
            "coverage": {
                "latest_available_date": "2026-08-31",
                "requires_api_key": False,
            },
        }
    }
    with patch(_GET, return_value=_response(body=body)):
        result = _run(action="indicator_catalogue", currency="usd")
    assert json.loads(result.content)["indicators"] == [
        {
            "indicator": "inflation",
            "name": "Inflation (CPI)",
            "unit": "%",
            "latest_available_date": "2026-08-31",
            "requires_api_key": False,
        }
    ]
    with patch(_GET, return_value=_response(body={})):
        assert not _run(action="indicator_catalogue", currency="usd").success


def test_fx_rates_map_rows():
    body = {
        "data": [{"date": "2026-10-06", "val": 1.0931}],
        "pagination": {"has_more": True, "total_count": 300},
    }
    with patch(_GET, return_value=_response(body=body)) as get:
        result = _run(
            FXMacroDataTool(api_key=_KEY),
            action="fx_rates",
            base="eur",
            quote="usd",
            limit=1,
        )
    assert get.call_args.args[0].endswith("/forex/eur/usd")
    data = json.loads(result.content)
    assert data["pair"] == "EUR/USD"
    assert data["rates"] == [{"date": "2026-10-06", "rate": 1.0931}]
    assert data["pagination"]["has_more"] is True
