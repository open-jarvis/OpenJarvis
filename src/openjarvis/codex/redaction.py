"""Credential-safe serialization for Codex health, events, and errors."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

from openjarvis.security.credential_stripper import CredentialStripper

_SENSITIVE_KEY_PARTS = (
    "access_token",
    "accesstoken",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "refresh_token",
    "refreshtoken",
    "secret",
)
_SENSITIVE_ENV_PARTS = (
    "API_KEY",
    "ACCESS_TOKEN",
    "AUTHORIZATION",
    "COOKIE",
    "REFRESH_TOKEN",
)
_JWT_PATTERN = re.compile(
    r"\beyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\b"
)
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|"
    r"cookie|password|secret)\b(\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)


def redact_text(text: str) -> str:
    """Redact common credential formats from arbitrary text."""

    stripped = CredentialStripper().strip(text)
    stripped = _JWT_PATTERN.sub("[REDACTED:token]", stripped)
    return _ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        stripped,
    )


def redact_data(value: Any) -> Any:
    """Recursively redact sensitive keys and credential-like strings."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                redacted[key_text] = "[REDACTED]" if item is not None else None
            else:
                redacted[key_text] = redact_data(item)
        return redacted
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_data(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def sanitized_codex_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy an environment without API-key or token fallback variables."""

    environment = source if source is not None else os.environ
    return {
        key: value
        for key, value in environment.items()
        if not any(part in key.upper() for part in _SENSITIVE_ENV_PARTS)
    }


def safe_error_message(error: BaseException) -> str:
    """Return an exception message suitable for logs and API responses."""

    return redact_text(str(error))


__all__ = [
    "redact_data",
    "redact_text",
    "safe_error_message",
    "sanitized_codex_environment",
]
