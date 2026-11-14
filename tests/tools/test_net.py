"""Tests for the key-free network helpers (RSS, crypto, FX, weather, units)."""

from __future__ import annotations

from types import SimpleNamespace

from openjarvis.tools.net import (
    convert_units,
    crypto_prices,
    currency_rate,
    headlines_for,
    rss_headlines,
    weather_now,
)


def _fake_response(text: str = "", data: dict | None = None) -> SimpleNamespace:
    def raise_for_status():
        return None

    return SimpleNamespace(
        text=text,
        json=lambda: data or {},
        raise_for_status=raise_for_status,
    )


RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Premier titre</title><link>http://x/1</link></item>
  <item><title>Premier titre</title><link>http://x/2</link></item>
  <item><title>Second   titre</title><link>http://x/3</link></item>
</channel></rss>"""


def test_rss_headlines_parses_and_dedupes(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.tools.net.httpx.get",
        lambda url, **kwargs: _fake_response(text=RSS_XML),
    )
    assert rss_headlines(["http://feed"]) == ["Premier titre", "Second titre"]


def test_headlines_for_unknown_category_raises() -> None:
    import pytest

    with pytest.raises(RuntimeError) as excinfo:
        headlines_for("inexistant")
    assert "Catégorie inconnue" in str(excinfo.value)


def test_crypto_prices_parses_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.tools.net.httpx.get",
        lambda url, **kwargs: _fake_response(
            data={"bitcoin": {"eur": 61000.5}, "ethereum": {"eur": 2100.25}}
        ),
    )
    prices = crypto_prices()
    assert prices == {"bitcoin": 61000.5, "ethereum": 2100.25}


def test_currency_rate_parses_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.tools.net.httpx.get",
        lambda url, **kwargs: _fake_response(data={"rates": {"EUR": 0.92}}),
    )
    assert currency_rate("usd", "eur") == 0.92


def test_currency_rate_unknown_target_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.tools.net.httpx.get",
        lambda url, **kwargs: _fake_response(data={"rates": {"EUR": 0.92}}),
    )
    import pytest

    with pytest.raises(RuntimeError) as excinfo:
        currency_rate("usd", "zzz")
    assert "Devise inconnue" in str(excinfo.value)


def test_weather_now_trims_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.tools.net.httpx.get",
        lambda url, **kwargs: _fake_response(text=" Paris : ⛅  +8°C \n"),
    )
    assert weather_now("paris") == "Paris : ⛅ +8°C"


def test_convert_units_length_and_temperature() -> None:
    assert convert_units("5 km en miles") == "5 km = 3.10685 miles"
    assert convert_units("100 kg en livres") == "100 kg = 220.462 livres"
    assert convert_units("20 c en f") == "20 c = 68 f"
    assert convert_units("68 f en c") == "68 f = 20 c"


def test_convert_units_rejects_unsupported() -> None:
    assert convert_units("hello world") is None
    assert convert_units("5 pommes en poires") is None
