"""Validate publisher-only team connections (Buffer, Cloudflare R2).

These connections hold a company's own credential and are used only by the
server-side publisher after human approval. They are never exposed to agents.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple
from urllib.parse import urlsplit

BUFFER_API_URL = "https://api.buffer.com"
DEFAULT_TIMEZONE = "Africa/Cairo"


def _text(settings: Dict[str, Any], key: str, pattern: str, label: str) -> str:
    value = str(settings.get(key) or "").strip()
    if not re.fullmatch(pattern, value):
        raise ValueError(f"{label} غير صالح")
    return value


def normalize_provider_settings(
    kind: str, url: str, settings: Dict[str, Any]
) -> Tuple[str, Dict[str, Any]]:
    """Return the fixed endpoint and the non-secret settings to store."""
    from zoneinfo import ZoneInfo

    timezone = str(settings.get("timezone") or DEFAULT_TIMEZONE)
    try:
        ZoneInfo(timezone)
    except Exception:
        raise ValueError("Unknown timezone") from None
    if kind == "buffer":
        clean: Dict[str, Any] = {"timezone": timezone}
        for key in ("organization_id", "channel_id"):
            if settings.get(key):
                clean[key] = _text(settings, key, r"[A-Za-z0-9_-]{1,64}", key)
        return BUFFER_API_URL, clean
    if kind == "r2":
        account = _text(
            settings, "account_id", r"[0-9a-f]{32}", "Cloudflare account ID"
        )
        bucket = _text(
            settings, "bucket", r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", "R2 bucket"
        )
        access_key = _text(
            settings, "access_key_id", r"[A-Za-z0-9]{16,128}", "R2 access key ID"
        )
        public = str(settings.get("public_base_url") or "").strip().rstrip("/")
        parsed = urlsplit(public)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "Public base URL must be the bucket's public HTTPS address "
                "(r2.dev or custom domain) without credentials or query"
            )
        return f"https://{account}.r2.cloudflarestorage.com", {
            "account_id": account,
            "bucket": bucket,
            "access_key_id": access_key,
            "public_base_url": public,
            "timezone": timezone,
        }
    raise ValueError("Unsupported connection kind")


__all__ = ["BUFFER_API_URL", "DEFAULT_TIMEZONE", "normalize_provider_settings"]
