"""Tests for technical indicator functions (pure, deterministic)."""

from __future__ import annotations

from openjarvis.finance import indicators


def test_sma_basic():
    assert indicators.sma([1, 2, 3, 4, 5], 5) == 3.0
    assert indicators.sma([2, 4, 6], 3) == 4.0


def test_sma_insufficient_data():
    assert indicators.sma([1, 2], 5) is None


def test_ema_returns_value():
    values = [float(i) for i in range(1, 30)]
    e = indicators.ema(values, 10)
    assert e is not None
    # EMA of a rising series sits below the latest price but above the SMA.
    assert e < values[-1]


def test_rsi_all_gains_is_100():
    rising = [float(i) for i in range(1, 30)]
    assert indicators.rsi(rising, 14) == 100.0


def test_rsi_mid_range_for_choppy_series():
    # Alternating up/down keeps RSI near the middle of the range.
    choppy = []
    price = 100.0
    for i in range(40):
        price += 1.0 if i % 2 == 0 else -1.0
        choppy.append(price)
    r = indicators.rsi(choppy, 14)
    assert r is not None
    assert 30 < r < 70


def test_macd_returns_triple():
    values = [float(i) for i in range(1, 80)]
    result = indicators.macd(values)
    assert result is not None
    macd_line, signal_line, hist = result
    assert isinstance(macd_line, float)
    assert isinstance(signal_line, float)
    assert abs(hist - (macd_line - signal_line)) < 1e-9


def test_macd_insufficient_data():
    assert indicators.macd([1.0, 2.0, 3.0]) is None


def test_summarize_bullish_on_uptrend():
    values = [float(i) for i in range(1, 80)]
    s = indicators.summarize(values)
    assert s["bias"] == "bullish"
    assert s["sma20"] is not None
    assert s["rsi14"] is not None
