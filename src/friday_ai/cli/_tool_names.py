"""Helpers for resolving CLI tool selections."""

from __future__ import annotations

from typing import Any


def _normalize_tool_names(value: Any) -> list[str]:
    """Normalize configured tool names from string or list-like values."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        names = []
        for item in value:
            text = str(item).strip()
            if text:
                names.append(text)
        return names

    text = str(value).strip()
    return [text] if text else []


def resolve_tool_names(
    cli_value: str | None,
    *configured_values: Any,
) -> list[str]:
    """Resolve tool names, preferring explicit CLI values over config fallbacks."""
    cli_names = _normalize_tool_names(cli_value)
    if cli_names:
        return cli_names

    for configured in configured_values:
        names = _normalize_tool_names(configured)
        if names:
            return names

    return []
