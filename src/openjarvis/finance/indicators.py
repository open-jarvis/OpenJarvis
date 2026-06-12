"""Pure technical-analysis functions operating on close-price series.

All functions take a list of floats ordered oldest → newest and return plain
Python numbers/lists. No third-party dependencies (no numpy/pandas) so they run
anywhere the rest of OpenJarvis runs.
"""

from __future__ import annotations

from typing import List, Optional, Tuple


def sma(values: List[float], period: int) -> Optional[float]:
    """Simple moving average of the last *period* values."""
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def ema_series(values: List[float], period: int) -> List[float]:
    """Full exponential moving average series (same length as input).

    Seeds with the SMA of the first *period* values, then applies the standard
    EMA recurrence. Returns an empty list when there is not enough data.
    """
    if period <= 0 or len(values) < period:
        return []
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out: List[float] = [seed]
    for price in values[period:]:
        out.append(price * k + out[-1] * (1 - k))
    return out


def ema(values: List[float], period: int) -> Optional[float]:
    """Latest exponential moving average value."""
    series = ema_series(values, period)
    return series[-1] if series else None


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    """Wilder's Relative Strength Index for the latest bar (0–100)."""
    if period <= 0 or len(values) <= period:
        return None
    gains = 0.0
    losses = 0.0
    # Seed average gain/loss over the first `period` deltas.
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    # Wilder smoothing across the remaining deltas.
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    values: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[Tuple[float, float, float]]:
    """Return (macd_line, signal_line, histogram) for the latest bar."""
    if len(values) < slow + signal:
        return None
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    # Align the two EMA series on their newest values.
    n = min(len(fast_series), len(slow_series))
    macd_line = [fast_series[-n + i] - slow_series[-n + i] for i in range(n)]
    signal_series = ema_series(macd_line, signal)
    if not signal_series:
        return None
    macd_val = macd_line[-1]
    signal_val = signal_series[-1]
    return macd_val, signal_val, macd_val - signal_val


def summarize(values: List[float]) -> dict:
    """Compute a standard indicator bundle and a naive bias signal."""
    last = values[-1] if values else None
    sma20 = sma(values, 20)
    sma50 = sma(values, 50)
    rsi14 = rsi(values, 14)
    macd_tuple = macd(values)

    # Bias is driven by trend signals (price vs SMA, SMA cross, MACD). RSI
    # extremes are reported but not voted: overbought conditions routinely
    # persist through strong uptrends, so treating them as bearish votes
    # produces false neutrality on healthy trends.
    signals: List[str] = []
    bull = 0
    bear = 0
    _eps = 1e-9

    if last is not None and sma20 is not None:
        if last > sma20:
            signals.append("price > SMA20")
            bull += 1
        elif last < sma20:
            signals.append("price < SMA20")
            bear += 1
    if sma20 is not None and sma50 is not None:
        if sma20 > sma50:
            signals.append("SMA20 > SMA50 (bullish)")
            bull += 1
        elif sma20 < sma50:
            signals.append("SMA20 < SMA50 (bearish)")
            bear += 1
    if macd_tuple is not None:
        hist = macd_tuple[2]
        if hist > _eps:
            signals.append("MACD bullish")
            bull += 1
        elif hist < -_eps:
            signals.append("MACD bearish")
            bear += 1
    if rsi14 is not None:
        if rsi14 >= 70:
            signals.append("RSI overbought (caution)")
        elif rsi14 <= 30:
            signals.append("RSI oversold (caution)")

    bias = "neutral"
    if bull > bear:
        bias = "bullish"
    elif bear > bull:
        bias = "bearish"

    return {
        "last": last,
        "sma20": sma20,
        "sma50": sma50,
        "rsi14": rsi14,
        "macd": macd_tuple,
        "signals": signals,
        "bias": bias,
    }


__all__ = ["sma", "ema", "ema_series", "rsi", "macd", "summarize"]
