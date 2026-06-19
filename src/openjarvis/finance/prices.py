"""Price feeds for crypto (CoinGecko) and stocks (Stooq).

Both providers are free and require no API key. Low-level HTTP calls are kept in
``_coingecko_get`` / ``_stooq_get_csv`` so tests can patch them without network.
"""

from __future__ import annotations

from typing import Any, Dict, List

_COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
_UA = "Mozilla/5.0 (compatible; OpenJarvis/1.0; +https://github.com/openjarvis)"
_TIMEOUT = 20.0

# Common ticker → CoinGecko id aliases. Unknown symbols are passed through as-is
# (callers may supply a CoinGecko id directly, e.g. "the-open-network").
_CRYPTO_IDS: Dict[str, str] = {
    "btc": "bitcoin",
    "xbt": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "ada": "cardano",
    "xrp": "ripple",
    "doge": "dogecoin",
    "dot": "polkadot",
    "matic": "matic-network",
    "ltc": "litecoin",
    "bch": "bitcoin-cash",
    "link": "chainlink",
    "avax": "avalanche-2",
    "bnb": "binancecoin",
    "usdt": "tether",
    "usdc": "usd-coin",
    "trx": "tron",
    "ton": "the-open-network",
}


class PriceError(RuntimeError):
    """Raised when a price lookup fails or returns no usable data."""


# ---------------------------------------------------------------------------
# Low-level HTTP (patched in tests)
# ---------------------------------------------------------------------------


def _coingecko_get(path: str, params: Dict[str, Any]) -> Any:
    import httpx

    resp = httpx.get(f"{_COINGECKO_BASE}{path}", params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _yahoo_get_chart(
    symbol: str, *, range_: str = "6mo", interval: str = "1d"
) -> Dict[str, Any]:
    import httpx

    resp = httpx.get(
        f"{_YAHOO_CHART}{symbol.upper()}",
        params={"range": range_, "interval": interval},
        headers={"User-Agent": _UA},
        timeout=_TIMEOUT,
        follow_redirects=True,
    )
    resp.raise_for_status()
    data = resp.json()
    chart = data.get("chart") or {}
    if chart.get("error"):
        raise PriceError(f"Yahoo error for '{symbol}': {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise PriceError(f"No data returned for symbol '{symbol}'.")
    return results[0]


# ---------------------------------------------------------------------------
# Crypto (CoinGecko)
# ---------------------------------------------------------------------------


def resolve_crypto_id(symbol: str) -> str:
    """Map a ticker to a CoinGecko coin id (pass-through for unknown symbols)."""
    s = symbol.strip().lower()
    return _CRYPTO_IDS.get(s, s)


def get_crypto_price(symbol: str, vs_currency: str = "usd") -> Dict[str, Any]:
    """Return current price + 24h change for a crypto asset."""
    coin_id = resolve_crypto_id(symbol)
    vs = vs_currency.strip().lower()
    data = _coingecko_get(
        "/simple/price",
        {
            "ids": coin_id,
            "vs_currencies": vs,
            "include_24hr_change": "true",
        },
    )
    if not isinstance(data, dict) or coin_id not in data:
        raise PriceError(f"Unknown crypto symbol '{symbol}' (id '{coin_id}').")
    entry = data[coin_id]
    price = entry.get(vs)
    if price is None:
        raise PriceError(f"No {vs.upper()} price for '{coin_id}'.")
    return {
        "symbol": symbol.upper(),
        "id": coin_id,
        "price": float(price),
        "currency": vs.upper(),
        "change_24h": entry.get(f"{vs}_24h_change"),
        "source": "coingecko",
    }


def get_crypto_series(symbol: str, days: int = 30, vs_currency: str = "usd") -> List[float]:
    """Return a list of historical closing prices (oldest → newest)."""
    coin_id = resolve_crypto_id(symbol)
    data = _coingecko_get(
        f"/coins/{coin_id}/market_chart",
        {"vs_currency": vs_currency.strip().lower(), "days": max(1, int(days))},
    )
    prices = (data or {}).get("prices") or []
    series = [float(p[1]) for p in prices if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not series:
        raise PriceError(f"No price history for crypto '{coin_id}'.")
    return series


# ---------------------------------------------------------------------------
# Stocks (Yahoo Finance chart API)
# ---------------------------------------------------------------------------


def _range_for_days(days: int) -> str:
    """Pick the smallest Yahoo range that covers *days* of daily bars."""
    if days <= 5:
        return "5d"
    if days <= 25:
        return "1mo"
    if days <= 65:
        return "3mo"
    if days <= 125:
        return "6mo"
    if days <= 250:
        return "1y"
    if days <= 500:
        return "2y"
    return "5y"


def _last_non_null(values: List[Any]) -> Any:
    for v in reversed(values or []):
        if v is not None:
            return v
    return None


def get_stock_quote(symbol: str) -> Dict[str, Any]:
    """Return the latest OHLCV quote for a stock/ETF symbol."""
    from datetime import datetime, timezone

    result = _yahoo_get_chart(symbol, range_="5d", interval="1d")
    meta = result.get("meta") or {}
    quote_blocks = (result.get("indicators") or {}).get("quote") or [{}]
    q = quote_blocks[0] if quote_blocks else {}

    price = meta.get("regularMarketPrice")
    if price is None:
        price = _last_non_null(q.get("close", []))
    if price is None:
        raise PriceError(f"No price available for symbol '{symbol}'.")

    ts = meta.get("regularMarketTime")
    date = ""
    if ts:
        try:
            date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            date = ""

    return {
        "symbol": (meta.get("symbol") or symbol).upper(),
        "price": float(price),
        "open": _last_non_null(q.get("open", [])),
        "high": _last_non_null(q.get("high", [])),
        "low": _last_non_null(q.get("low", [])),
        "volume": _last_non_null(q.get("volume", [])),
        "date": date,
        "source": "yahoo",
    }


def get_stock_series(symbol: str, days: int = 120) -> List[float]:
    """Return historical daily closing prices (oldest → newest), last *days*."""
    n = max(2, int(days))
    result = _yahoo_get_chart(symbol, range_=_range_for_days(n), interval="1d")
    quote_blocks = (result.get("indicators") or {}).get("quote") or [{}]
    closes_raw = quote_blocks[0].get("close", []) if quote_blocks else []
    closes = [float(c) for c in closes_raw if c is not None]
    if not closes:
        raise PriceError(f"No price history for stock '{symbol}'.")
    return closes[-n:]


# ---------------------------------------------------------------------------
# Unified helpers
# ---------------------------------------------------------------------------


def get_price(symbol: str, asset_type: str) -> float:
    """Return the current price for a crypto or stock asset."""
    if asset_type == "crypto":
        return float(get_crypto_price(symbol)["price"])
    return float(get_stock_quote(symbol)["price"])


def get_series(symbol: str, asset_type: str, days: int) -> List[float]:
    """Return a historical close series for a crypto or stock asset."""
    if asset_type == "crypto":
        return get_crypto_series(symbol, days=days)
    return get_stock_series(symbol, days=days)


__all__ = [
    "PriceError",
    "resolve_crypto_id",
    "get_crypto_price",
    "get_crypto_series",
    "get_stock_quote",
    "get_stock_series",
    "get_price",
    "get_series",
]
