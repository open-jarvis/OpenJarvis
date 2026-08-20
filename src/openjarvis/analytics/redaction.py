"""PII redaction for analytics property values.

This is the value-level half of the guardrail
(:mod:`openjarvis.analytics.events` is the structural half).

For each property value we ship, we:
  1. Drop strings longer than ``MAX_STR_LEN`` (no chunks of chat content).
  2. Drop strings that match any known PII pattern (emails, IPs, MACs,
     $HOME paths, API keys, JWTs, bearer tokens, etc.).
  3. Otherwise pass through unchanged.

Fail-closed: when in doubt, drop. Combined with the event-spec
allowlist this gives two independent layers of protection.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

MAX_STR_LEN = 200

# Patterns that, if found anywhere inside a string value, cause that
# value to be dropped. Order is by likelihood for short-circuit speed.
_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Email
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    # IPv4 (any 4-octet decimal pattern)
    re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    # IPv6 (loose — any colon-separated hex)
    re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){2,}[0-9A-Fa-f]{0,4}\b"),
    # MAC address
    re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b"),
    # Home paths
    re.compile(r"/Users/[^/\s]+"),
    re.compile(r"/home/[^/\s]+"),
    re.compile(r"\$HOME|~/"),
    # File URLs
    re.compile(r"file://"),
    # Common API key prefixes
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),  # OpenAI / Anthropic
    re.compile(r"\bxoxb-[A-Za-z0-9-]{8,}"),  # Slack bot
    re.compile(r"\bxoxp-[A-Za-z0-9-]{8,}"),  # Slack user
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),  # GitHub personal
    re.compile(r"\bgho_[A-Za-z0-9]{20,}"),  # GitHub OAuth
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),  # Google API key
    re.compile(r"\bya29\.[0-9A-Za-z_-]+"),  # Google OAuth access token
    # JWT (three base64url chunks separated by dots, header starts with eyJ)
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    # Bearer authorization headers
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]+"),
    # Password / secret assignment patterns
    re.compile(r"(?i)\b(password|secret|api_key|token)\s*[:=]\s*\S+"),
    # Hostnames that look like personal machines (e.g. johns-macbook.local)
    re.compile(r"\b[A-Za-z0-9-]+\.local\b"),
)


def looks_like_pii(s: str) -> bool:
    """Return True if any PII pattern matches anywhere in ``s``."""
    for pattern in _PII_PATTERNS:
        if pattern.search(s):
            return True
    return False


def redact(properties: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``properties`` with PII-bearing string values dropped.

    Non-string values pass through unchanged. Strings exceeding
    ``MAX_STR_LEN`` are dropped. Strings matching any PII pattern are
    dropped. The event-spec validator (in :mod:`events`) runs after
    this and provides a second layer of structural enforcement.
    """
    out: dict[str, Any] = {}
    for key, value in properties.items():
        if isinstance(value, str):
            if not value:
                # empty string is uninformative — drop
                continue
            if len(value) > MAX_STR_LEN:
                continue
            if looks_like_pii(value):
                continue
        elif isinstance(value, (list, dict, set, tuple)):
            # Composite values are never sent — keeps the surface tiny.
            continue
        out[key] = value
    return out


def hash_id(s: str) -> str:
    """Return a 16-char sha256 prefix of ``s``.

    Used for model / tool / connector names that aren't on the public
    allowlist — we still want to see "uses-a-custom-model-X" cohorting
    without ever learning which model.
    """
    if not s:
        return ""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


__all__ = ["MAX_STR_LEN", "redact", "looks_like_pii", "hash_id"]
