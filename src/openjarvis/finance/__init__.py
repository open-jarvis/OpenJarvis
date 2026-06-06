"""Finance primitives: price feeds, technical indicators, and local stores.

All providers are free and key-free by default (CoinGecko for crypto, Stooq for
stocks). Network calls live in module-level functions so they are trivially
mockable in tests.
"""

from __future__ import annotations

__all__ = ["prices", "indicators", "store"]
