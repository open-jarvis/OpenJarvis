"""Live network information helpers — free APIs, no API keys.

Powers the JARVIS network commands (``/news``, ``/marchés``, ``/convert``,
``/brief``): RSS headlines, crypto prices (CoinGecko), currency rates
(open.er-api.com), weather (wttr.in) and local unit conversion. Every call
is bounded by a short timeout and surfaces a clear error when the network
or the service is unavailable, so the assistant never hangs on connectivity.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0
_USER_AGENT = "OpenJarvis/1.0 (local assistant)"

# Public, key-free RSS feeds grouped by category (French + world coverage).
RSS_FEEDS: dict[str, list[str]] = {
    "monde": [
        "https://www.lemonde.fr/international/rss_full.xml",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
    ],
    "tech": [
        "https://www.lemonde.fr/pixels/rss_full.xml",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
    ],
    "economie": [
        "https://www.lemonde.fr/economie/rss_full.xml",
    ],
    "sport": [
        "https://www.lemonde.fr/sport/rss_full.xml",
        "https://feeds.bbci.co.uk/sport/rss.xml",
    ],
    "culture": [
        "https://www.lemonde.fr/culture/rss_full.xml",
    ],
    "science": [
        "https://www.lemonde.fr/sciences/rss_full.xml",
        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    ],
}


def _get(url: str, **kwargs) -> httpx.Response:
    """GET with the assistant's user agent and a short timeout."""
    kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
    kwargs.setdefault("follow_redirects", True)
    kwargs.setdefault("headers", {"User-Agent": _USER_AGENT})
    return httpx.get(url, **kwargs)


def rss_headlines(feeds: List[str], limit: int = 8) -> List[str]:
    """Fetch RSS feeds and return deduplicated, trimmed headlines."""
    seen: set[str] = set()
    titles: List[str] = []
    for url in feeds:
        try:
            response = _get(url)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            for item in root.iter("item"):
                title = item.findtext("title") or ""
                title = re.sub(r"\s+", " ", title).strip()
                if title and title not in seen:
                    seen.add(title)
                    titles.append(title)
                if len(titles) >= limit:
                    return titles
        except Exception as exc:  # noqa: BLE001 — one dead feed must not fail all
            logger.debug("RSS fetch failed for %s: %s", url, exc)
            continue
    return titles


def headlines_for(category: str = "", limit: int = 8) -> List[str]:
    """Headlines for *category*, or across all feeds when empty."""
    if category:
        feeds = RSS_FEEDS.get(category)
        if feeds is None:
            raise RuntimeError(
                f"Catégorie inconnue '{category}'. Disponibles : "
                + ", ".join(sorted(RSS_FEEDS))
            )
    else:
        feeds = [url for urls in RSS_FEEDS.values() for url in urls]
    return rss_headlines(feeds, limit=limit)


def crypto_prices(
    ids: tuple = ("bitcoin", "ethereum"),
    currency: str = "eur",
) -> dict[str, float]:
    """Current crypto prices via CoinGecko (free, no key)."""
    response = _get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": ",".join(ids), "vs_currencies": currency},
    )
    response.raise_for_status()
    data = response.json()
    return {
        name: float(prices[currency])
        for name, prices in data.items()
        if currency in prices
    }


def currency_rate(from_cur: str, to_cur: str) -> float:
    """Exchange rate via open.er-api.com (free, no key)."""
    from_cur = from_cur.upper()
    to_cur = to_cur.upper()
    response = _get(f"https://open.er-api.com/v6/latest/{from_cur}")
    response.raise_for_status()
    rates = response.json().get("rates") or {}
    rate = rates.get(to_cur)
    if rate is None:
        raise RuntimeError(f"Devise inconnue : {to_cur}")
    return float(rate)


def weather_now(city: str = "") -> str:
    """Current weather as a short French phrase via wttr.in (free, no key)."""
    target = city.strip().replace(" ", "+")
    url = f"https://wttr.in/{target}" if target else "https://wttr.in/"
    response = _get(url, params={"format": "3", "lang": "fr"})
    response.raise_for_status()
    return re.sub(r"\s+", " ", response.text).strip()


# -- local unit conversion (no network) --------------------------------------


def _unit_key(word: str) -> Optional[str]:
    mapping = {
        "km": "km",
        "kilomètre": "km",
        "kilomètres": "km",
        "mile": "mi",
        "miles": "mi",
        "m": "m",
        "mètre": "m",
        "mètres": "m",
        "ft": "ft",
        "pied": "ft",
        "pieds": "ft",
        "kg": "kg",
        "kilo": "kg",
        "kilos": "kg",
        "lb": "lb",
        "lbs": "lb",
        "livre": "lb",
        "livres": "lb",
        "c": "c",
        "°c": "c",
        "f": "f",
        "°f": "f",
    }
    return mapping.get(word.lower().rstrip("s"))


def convert_units(text: str) -> Optional[str]:
    """Convert local units, e.g. ``5 km en miles`` or ``20 c en f``.

    Returns the formatted conversion or ``None`` when the text is not a
    supported unit conversion.
    """
    match = re.match(
        r"^\s*([\d.,]+)\s*([A-Za-z°]+)\s+(?:en|to|vers)\s+([A-Za-z°]+)\s*$",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        amount = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    source, target = match.group(2), match.group(3)
    key_from = _unit_key(source)
    key_to = _unit_key(target)
    if key_from is None or key_to is None or key_from == key_to:
        return None

    # (from, to) → factor, or a temperature function.
    factors = {
        ("km", "mi"): 0.621371,
        ("mi", "km"): 1.60934,
        ("m", "ft"): 3.28084,
        ("ft", "m"): 0.3048,
        ("kg", "lb"): 2.20462,
        ("lb", "kg"): 0.453592,
    }
    pair = (key_from, key_to)
    if pair == ("c", "f"):
        result = amount * 9 / 5 + 32
    elif pair == ("f", "c"):
        result = (amount - 32) * 5 / 9
    elif pair in factors:
        result = amount * factors[pair]
    else:
        return None

    return f"{amount:g} {source} = {result:.6g} {target}"


__all__ = [
    "RSS_FEEDS",
    "convert_units",
    "crypto_prices",
    "currency_rate",
    "headlines_for",
    "rss_headlines",
    "weather_now",
]
