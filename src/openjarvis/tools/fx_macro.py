"""Native FX and macroeconomic data tool backed by the FXMacroData REST API.

The tool answers four kinds of question: the release history of one indicator
(CPI, policy rate, payrolls, GDP...), the upcoming release calendar, the list of
indicators published for a currency, and daily FX rates. USD releases from the
last 90 days, the USD calendar and every currency's catalogue answer without a
key; other currencies, full history and FX rates need ``FXMACRODATA_API_KEY``.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import httpx

from openjarvis.core.credentials import get_tool_credential
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_TOOL_NAME = "fx_macro_data"
_API_KEY_ENV = "FXMACRODATA_API_KEY"
_BASE_URL = "https://api.fxmacrodata.com/v1"
_ACTIONS = ("indicator_history", "release_calendar", "indicator_catalogue", "fx_rates")
_CURRENCY_PATTERN = re.compile(r"^[A-Za-z]{3}$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20
_STATUS_DETAILS = {
    400: "the request was invalid",
    401: "an API key is required for this request, or the key was rejected",
    403: "the API key does not cover this request",
    404: "the currency or indicator was not found",
    422: "the request parameters were rejected",
    429: "the rate limit was exceeded",
}


class FXMacroDataError(RuntimeError):
    """A credential-safe error from the FXMacroData API."""


def _api_get(path: str, params: dict[str, str], api_key: str | None) -> Any:
    """GET one fixed API path. Redirects are refused so the key never moves."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        resp = httpx.get(
            f"{_BASE_URL}{path}",
            params=params,
            headers=headers,
            timeout=30.0,
            follow_redirects=False,
        )
    except httpx.TimeoutException:
        raise FXMacroDataError("FXMacroData did not answer in time") from None
    except httpx.HTTPError:
        # Transport errors can format the request; never interpolate them.
        raise FXMacroDataError("FXMacroData could not be reached") from None
    if resp.is_redirect:
        raise FXMacroDataError("FXMacroData answered with an unexpected redirect")
    if resp.status_code != 200:
        detail = _STATUS_DETAILS.get(resp.status_code, "the request failed")
        raise FXMacroDataError(
            f"FXMacroData returned HTTP {resp.status_code}: {detail}"
        )
    try:
        payload = resp.json()
    except ValueError:
        raise FXMacroDataError("FXMacroData returned a non-JSON response") from None
    if not isinstance(payload, dict):
        raise FXMacroDataError("FXMacroData returned an unexpected response shape")
    if "detail" in payload and "data" not in payload:
        raise FXMacroDataError("FXMacroData returned an error response")
    return payload


def _currency(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _CURRENCY_PATTERN.fullmatch(value.strip()):
        raise ValueError(f"{field} must be a three-letter currency code such as USD.")
    return value.strip().lower()


def _slug(value: Any, field: str) -> str:
    text = value.strip().lower() if isinstance(value, str) else ""
    if not _SLUG_PATTERN.fullmatch(text):
        raise ValueError(
            f"{field} must be an indicator slug such as 'inflation' or "
            "'policy_rate'; use action='indicator_catalogue' to list them."
        )
    return text


def _date(value: Any, field: str) -> date | None:
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else ""
    if not _DATE_PATTERN.fullmatch(text):
        raise ValueError(f"{field} must be a date in YYYY-MM-DD form.")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{field} is not a real calendar date.") from None


def _date_params(params: dict[str, Any]) -> dict[str, str]:
    start = _date(params.get("start_date"), "start_date")
    end = _date(params.get("end_date"), "end_date")
    if start and end and start > end:
        raise ValueError("start_date must be on or before end_date.")
    out = {}
    if start:
        out["start_date"] = start.isoformat()
    if end:
        out["end_date"] = end.isoformat()
    return out


def _limit(value: Any) -> int:
    if value is None:
        return _DEFAULT_LIMIT
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"limit must be an integer from 1 to {_MAX_LIMIT}.")
    if not 1 <= value <= _MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}.")
    return value


def _rows(payload: dict[str, Any]) -> list[Any]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise FXMacroDataError("FXMacroData returned no data list")
    return rows


def _pagination(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return pagination, rejecting a present but malformed object."""
    if "pagination" not in payload:
        return None
    page = payload["pagination"]
    if not isinstance(page, dict) or not isinstance(page.get("has_more"), bool):
        raise FXMacroDataError("FXMacroData returned malformed pagination")
    return {"has_more": page["has_more"], "total_count": page.get("total_count")}


def _notices(payload: dict[str, Any]) -> list[str]:
    """Surface the keyless 90-day window and 15-minute delay when they apply."""
    notices = []
    for field in ("freemium_window", "freemium_delay"):
        block = payload.get(field)
        if isinstance(block, dict) and block.get("applied") is True:
            message = block.get("message")
            if isinstance(message, str) and message.strip():
                notices.append(message.strip())
    return notices


def _indicator_history(params: dict[str, Any], api_key: str | None) -> dict:
    currency = _currency(params.get("currency"), "currency")
    indicator = _slug(params.get("indicator"), "indicator")
    query = {**_date_params(params), "limit": str(_limit(params.get("limit")))}
    payload = _api_get(f"/announcements/{currency}/{indicator}", query, api_key)
    rows = [row for row in _rows(payload) if isinstance(row, dict)]
    return {
        "currency": currency.upper(),
        "indicator": indicator,
        "name": payload.get("name"),
        "source": payload.get("source"),
        "releases": [
            {
                "period": row.get("date"),
                "value": row.get("val"),
                "previous_value": row.get("previous_value"),
                "announced_at_utc": row.get("announcement_datetime"),
                "announced_at_local": row.get("announcement_datetime_local"),
                "source_url": row.get("source_url"),
            }
            for row in rows
        ],
        "pagination": _pagination(payload),
        "notices": _notices(payload),
    }


def _release_calendar(params: dict[str, Any], api_key: str | None) -> dict:
    currency = _currency(params.get("currency"), "currency")
    query = {}
    if params.get("indicator") is not None:
        query["indicator"] = _slug(params.get("indicator"), "indicator")
    limit = _limit(params.get("limit"))
    payload = _api_get(f"/calendar/{currency}", query, api_key)
    rows = [row for row in _rows(payload) if isinstance(row, dict)]
    return {
        "currency": currency.upper(),
        "events": [
            {
                "release": row.get("release"),
                "name": row.get("name"),
                "release_time_utc": row.get("announcement_datetime_utc"),
                "reference_period": row.get("date"),
                "importance": row.get("event_importance"),
            }
            for row in rows[:limit]
        ],
        "notices": _notices(payload),
    }


def _indicator_catalogue(params: dict[str, Any], api_key: str | None) -> dict:
    currency = _currency(params.get("currency"), "currency")
    payload = _api_get(f"/data_catalogue/{currency}", {}, api_key)
    indicators = []
    for slug, meta in payload.items():
        if not isinstance(meta, dict):
            continue
        coverage = meta.get("coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        indicators.append(
            {
                "indicator": slug,
                "name": meta.get("name"),
                "unit": meta.get("unit"),
                "latest_available_date": coverage.get("latest_available_date"),
                "requires_api_key": coverage.get("requires_api_key"),
            }
        )
    if not indicators:
        raise FXMacroDataError("FXMacroData returned an empty catalogue")
    return {"currency": currency.upper(), "indicators": indicators}


def _fx_rates(params: dict[str, Any], api_key: str | None) -> dict:
    base = _currency(params.get("base"), "base")
    quote = _currency(params.get("quote"), "quote")
    query = {**_date_params(params), "limit": str(_limit(params.get("limit")))}
    payload = _api_get(f"/forex/{base}/{quote}", query, api_key)
    rows = [row for row in _rows(payload) if isinstance(row, dict)]
    return {
        "pair": f"{base.upper()}/{quote.upper()}",
        "rates": [{"date": row.get("date"), "rate": row.get("val")} for row in rows],
        "pagination": _pagination(payload),
    }


_HANDLERS = {
    "indicator_history": _indicator_history,
    "release_calendar": _release_calendar,
    "indicator_catalogue": _indicator_catalogue,
    "fx_rates": _fx_rates,
}


@ToolRegistry.register(_TOOL_NAME)
class FXMacroDataTool(BaseTool):
    """Look up official macroeconomic releases, release calendars and FX rates."""

    tool_id = _TOOL_NAME
    is_local = False

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = (api_key or "").strip() or None

    def _resolve_api_key(self) -> str | None:
        if self._api_key:
            return self._api_key
        try:
            key = get_tool_credential(_TOOL_NAME, _API_KEY_ENV)
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        if isinstance(key, str) and key.strip():
            return key.strip()
        return None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=_TOOL_NAME,
            description=(
                "Official central-bank and statistics-office data for 22 "
                "currencies: an indicator's release history (CPI, policy rate, "
                "payrolls, GDP...), the upcoming release calendar, the list of "
                "indicators for a currency, and daily FX rates. USD releases "
                "from the last 90 days, the USD calendar and every catalogue "
                "work without an API key; other currencies, full history and "
                "FX rates need FXMACRODATA_API_KEY."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(_ACTIONS),
                        "description": "Which lookup to run.",
                    },
                    "currency": {
                        "type": "string",
                        "description": "Three-letter currency code, such as USD.",
                    },
                    "indicator": {
                        "type": "string",
                        "description": (
                            "Indicator slug such as 'inflation' or 'policy_rate'. "
                            "Required for indicator_history; optional filter for "
                            "release_calendar."
                        ),
                    },
                    "base": {
                        "type": "string",
                        "description": "Base currency for fx_rates, such as EUR.",
                    },
                    "quote": {
                        "type": "string",
                        "description": "Quote currency for fx_rates, such as USD.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Optional start date, YYYY-MM-DD.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Optional end date, YYYY-MM-DD.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_LIMIT,
                        "description": "Maximum rows to return (default 20).",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            category="finance",
            latency_estimate=1.0,
            timeout_seconds=30.0,
            required_capabilities=["network:fetch"],
            metadata={
                "provider": "fxmacrodata",
                "optional_api_key": _API_KEY_ENV,
                "credentials_configured": self._resolve_api_key() is not None,
            },
        )

    def execute(self, **params: Any) -> ToolResult:
        handler = _HANDLERS.get(params.get("action"))
        if handler is None:
            return self._failure(f"action must be one of: {', '.join(_ACTIONS)}.")
        api_key = self._resolve_api_key()
        try:
            result = handler(params, api_key)
        except ValueError as exc:
            return self._failure(str(exc))
        except FXMacroDataError as exc:
            return self._failure(f"FXMacroData lookup failed: {exc}")
        except Exception:
            return self._failure("FXMacroData lookup failed unexpectedly.")
        content = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if api_key:
            # Never hand the key back, even if the API echoed it in a field.
            content = content.replace(api_key, "[REDACTED]")
        return ToolResult(
            tool_name=_TOOL_NAME,
            content=content,
            success=True,
            metadata={"provider": "fxmacrodata", "action": params["action"]},
        )

    @staticmethod
    def _failure(message: str) -> ToolResult:
        return ToolResult(tool_name=_TOOL_NAME, content=message, success=False)


__all__ = ["FXMacroDataTool"]
