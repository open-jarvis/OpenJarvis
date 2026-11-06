"""The user's local time, for grounding prompts in their time zone.

Tools such as mail and calendar servers usually return timestamps in UTC.
Telling the model the user's time zone and current local time lets it
answer "08:54 UTC" as "10:54" for a user in Cairo.

The zone comes from, in order:

1. the request, via the ``X-OpenJarvis-Timezone`` header the web UI sends
   with chat and agent requests (the device's zone, or the one picked in
   Settings);
2. the last zone the UI sent, for agent runs with no request behind them
   (scheduled or queued work on this single-user server);
3. ``[system_prompt] timezone`` in config.toml;
4. the server machine's local zone.
"""

from __future__ import annotations

import contextvars
from datetime import datetime, timedelta, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIMEZONE_HEADER = "x-openjarvis-timezone"

_request_timezone: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "openjarvis_request_timezone", default=None
)
_last_client_timezone: Optional[str] = None


def valid_timezone(name: Optional[str]) -> Optional[str]:
    """Return ``name`` if it is a known IANA zone, else None."""
    if not name or len(name) > 64:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name


def set_request_timezone(name: Optional[str]) -> contextvars.Token:
    global _last_client_timezone
    zone = valid_timezone(name)
    if zone:
        _last_client_timezone = zone
    return _request_timezone.set(zone)


def reset_request_timezone(token: contextvars.Token) -> None:
    _request_timezone.reset(token)


def resolve_timezone(configured: str = "") -> tuple[Optional[str], tzinfo]:
    """Return the zone's IANA name (None for an unnamed local zone) and tzinfo."""
    name = (
        _request_timezone.get() or _last_client_timezone or valid_timezone(configured)
    )
    if name:
        return name, ZoneInfo(name)
    local = datetime.now().astimezone().tzinfo
    key = getattr(local, "key", None)
    return key, local  # type: ignore[return-value]


def _offset(delta: Optional[timedelta]) -> str:
    minutes = int((delta or timedelta()).total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{mins:02d}"


def current_time_section(configured: str = "", now: Optional[datetime] = None) -> str:
    """A short prompt section with the user's time zone and local time."""
    name, zone = resolve_timezone(configured)
    local = (now or datetime.now(zone)).astimezone(zone)
    label = (
        f"{name} ({_offset(local.utcoffset())})" if name else _offset(local.utcoffset())
    )
    return (
        "## Current Time\n\n"
        f"The user's time zone is {label}. "
        f"Their current local time is {local.strftime('%A %Y-%m-%d %H:%M')}. "
        "When you show dates or times, including ones a tool returns in UTC "
        "or another zone, convert them to the user's time zone and do not "
        "label them UTC."
    )
