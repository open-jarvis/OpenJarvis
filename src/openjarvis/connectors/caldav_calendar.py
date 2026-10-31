"""CalDAV calendar connector — read-only event sync from any CalDAV server.

Works with Nextcloud, Radicale, Baïkal, SOGo, Fastmail, iCloud and any other
server that speaks CalDAV (RFC 4791).  Requires the optional ``caldav``
package: ``pip install 'openjarvis[caldav]'``.

Credentials come from exactly one of these sources, checked in order (the
first one that sets a URL wins; sources are never mixed field by field):

1. Arguments passed to :class:`CalDAVConnector`.
2. Environment variables ``CALDAV_URL``, ``CALDAV_USERNAME``,
   ``CALDAV_PASSWORD`` and ``CALDAV_CALENDARS`` (comma-separated names).
3. ``~/.openjarvis/connectors/caldav.json`` (owner-only permissions), written
   by :meth:`CalDAVConnector.connect_with_credentials`.

The HTTP server does not accept CalDAV credentials; configure them locally.

All network calls are isolated in module-level functions
(``_caldav_fetch_events`` / ``_caldav_validate``) to keep them mockable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Sequence
from urllib.parse import urlparse

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import delete_tokens, load_tokens, save_tokens
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "caldav.json")
_DEFAULT_DAYS_AHEAD = 7
_DEFAULT_DAYS_BEHIND = 1
_REQUEST_TIMEOUT_SECONDS = 30
_INSTALL_HINT = "Install it with: pip install 'openjarvis[caldav]'"

_ENV_URL = "CALDAV_URL"
_ENV_USERNAME = "CALDAV_USERNAME"
_ENV_PASSWORD = "CALDAV_PASSWORD"
_ENV_CALENDARS = "CALDAV_CALENDARS"


@dataclass(frozen=True)
class _CalDAVSettings:
    """Resolved connection settings.  ``password`` is excluded from ``repr``."""

    url: str
    username: str
    password: str = field(repr=False)
    calendars: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return bool(self.url and self.username and self.password)


# ---------------------------------------------------------------------------
# Module-level network functions (easy to patch in tests)
# ---------------------------------------------------------------------------


def _import_caldav() -> Any:
    try:
        import caldav
    except ImportError as exc:
        raise RuntimeError(
            f"The CalDAV connector needs the 'caldav' package. {_INSTALL_HINT}"
        ) from exc
    return caldav


def _open_client(settings: _CalDAVSettings) -> Any:
    _validate_url(settings.url)
    caldav = _import_caldav()
    return caldav.DAVClient(
        url=settings.url,
        username=settings.username,
        password=settings.password,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )


def _calendar_name(calendar: Any) -> str:
    name = getattr(calendar, "name", None)
    if not name and hasattr(calendar, "get_display_name"):
        name = calendar.get_display_name()
    return str(name or "")


def _caldav_validate(settings: _CalDAVSettings) -> None:
    """Authenticate and list calendars; raise if the server rejects us."""
    client = _open_client(settings)
    try:
        client.principal().calendars()
    finally:
        client.close()


def _caldav_fetch_events(
    settings: _CalDAVSettings, start: datetime, end: datetime
) -> List[Dict[str, Any]]:
    """Return expanded events between *start* and *end* as plain dicts.

    Recurring events are expanded into one entry per occurrence.  When
    ``settings.calendars`` is non-empty only calendars with those display
    names (case-insensitive) are queried.
    """
    client = _open_client(settings)
    wanted = {name.casefold() for name in settings.calendars}
    events: List[Dict[str, Any]] = []
    try:
        for calendar in client.principal().calendars():
            name = _calendar_name(calendar)
            if wanted and name.casefold() not in wanted:
                continue
            for obj in calendar.search(start=start, end=end, event=True, expand=True):
                event = _vevent_to_dict(obj.icalendar_component, name)
                if event is not None:
                    events.append(event)
    finally:
        client.close()
    return events


# ---------------------------------------------------------------------------
# iCalendar helpers
# ---------------------------------------------------------------------------


def _decoded(component: Any, key: str) -> Any:
    prop = component.get(key)
    return None if prop is None else component.decoded(key)


def _to_local(value: date | datetime) -> date | datetime:
    """Convert aware datetimes to the machine's timezone; keep dates/floating."""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone()
    return value


def _strip_mailto(address: Any) -> str:
    text = str(address or "")
    return text[7:] if text.lower().startswith("mailto:") else text


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _text(component: Any, key: str) -> str:
    value = component.get(key)
    return str(value) if value is not None else ""


def _vevent_to_dict(component: Any, calendar_name: str) -> Optional[Dict[str, Any]]:
    """Normalize an ``icalendar`` VEVENT into a plain dict.

    Returns ``None`` for malformed events without ``DTSTART`` so one bad
    entry cannot abort the whole sync.
    """
    start = _decoded(component, "DTSTART")
    if start is None:
        return None
    end = _decoded(component, "DTEND")
    all_day = isinstance(start, date) and not isinstance(start, datetime)

    if end is None:
        duration = _decoded(component, "DURATION")
        if duration is not None:
            end = start + duration
        else:
            # RFC 5545 §3.6.1: no DTEND/DURATION means one day for all-day
            # events and zero length for timed events.
            end = start + timedelta(days=1) if all_day else start

    recurrence = component.get("RECURRENCE-ID")
    recurrence_id = recurrence.to_ical().decode() if recurrence is not None else None

    return {
        "uid": _text(component, "UID"),
        "summary": _text(component, "SUMMARY") or "(No title)",
        "start": _to_local(start),
        "end": _to_local(end),
        "all_day": all_day,
        "calendar": calendar_name,
        "location": _text(component, "LOCATION"),
        "description": _text(component, "DESCRIPTION"),
        "organizer": _strip_mailto(component.get("ORGANIZER")),
        "attendees": [_strip_mailto(a) for a in _as_list(component.get("ATTENDEE"))],
        "status": _text(component, "STATUS"),
        "recurrence_id": recurrence_id,
    }


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------


def _as_datetime(value: date | datetime) -> datetime:
    """Return a datetime for sorting/timestamps (all-day → local midnight)."""
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min)


def _aware(value: date | datetime) -> datetime:
    moment = _as_datetime(value)
    return moment if moment.tzinfo else moment.astimezone()


def _sort_key(event: Dict[str, Any], now: datetime) -> tuple[bool, datetime]:
    """Not-yet-finished events first, each group earliest first.

    The digest keeps only the first few documents per source, so events that
    already ended must not crowd out today's and upcoming ones.
    """
    return (_aware(event["end"]) <= now, _aware(event["start"]))


def _single_line(text: str) -> str:
    """Collapse newlines/tabs so event text cannot fake extra digest lines."""
    return " ".join(text.split())


def _format_event(event: Dict[str, Any]) -> str:
    lines = [
        f"Title: {_single_line(event['summary'])}",
        f"When: {event['start'].isoformat()} – {event['end'].isoformat()}",
        f"Calendar: {_single_line(event['calendar'])}",
    ]
    if event["location"]:
        lines.append(f"Location: {_single_line(event['location'])}")
    if event["organizer"]:
        lines.append(f"Organizer: {event['organizer']}")
    if event["attendees"]:
        lines.append(f"Attendees: {', '.join(event['attendees'])}")
    if event["description"]:
        lines.append(f"Description: {event['description']}")
    return "\n".join(lines)


def _event_to_document(event: Dict[str, Any]) -> Document:
    source_id = event["uid"]
    if event["recurrence_id"]:
        source_id = f"{source_id}:{event['recurrence_id']}"
    calendar = _single_line(event["calendar"])
    return Document(
        doc_id=f"caldav:{source_id}",
        source="caldav",
        doc_type="event",
        content=_format_event(event),
        title=_single_line(event["summary"]),
        author=event["organizer"],
        participants=list(event["attendees"]),
        timestamp=_as_datetime(event["start"]),
        metadata={
            "calendar": calendar,
            "uid": event["uid"],
            "start": event["start"].isoformat(),
            "end": event["end"].isoformat(),
            "all_day": event["all_day"],
            "location": _single_line(event["location"]),
            "status": event["status"],
        },
        source_id=source_id,
        participants_raw=list(event["attendees"]),
        channel=calendar,
    )


def _is_cancelled(event: Dict[str, Any]) -> bool:
    return event["status"].upper() == "CANCELLED"


def _parse_calendars(value: Any) -> tuple[str, ...]:
    items = value.split(",") if isinstance(value, str) else value or []
    return tuple(name.strip() for name in items if str(name).strip())


def _validate_url(url: str) -> None:
    # Messages never echo the URL: it could carry credentials.
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("CalDAV URL must start with http:// or https://")
    if parsed.username or parsed.password:
        raise ValueError(
            "CalDAV URL must not embed credentials; set the username and "
            "password separately"
        )


# ---------------------------------------------------------------------------
# CalDAVConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("caldav")
class CalDAVConnector(BaseConnector):
    """Read-only connector for calendars on any CalDAV server.

    Parameters
    ----------
    url:
        CalDAV endpoint, e.g. ``https://cloud.example.com/remote.php/dav``
        for Nextcloud.
    username, password:
        Account credentials.  Prefer an app password.
    calendars:
        Optional display names of the calendars to include (default: all).
    config_path:
        Credentials file.  Defaults to ``~/.openjarvis/connectors/caldav.json``.
    days_ahead, days_behind:
        Sync window around now when ``sync()`` gets no ``since``.
    """

    connector_id = "caldav"
    display_name = "CalDAV Calendar"
    auth_type = "local"

    def __init__(
        self,
        url: str = "",
        username: str = "",
        password: str = "",
        calendars: Optional[Sequence[str]] = None,
        *,
        config_path: str = "",
        days_ahead: int = _DEFAULT_DAYS_AHEAD,
        days_behind: int = _DEFAULT_DAYS_BEHIND,
    ) -> None:
        self._url = url
        self._username = username
        self._password = password
        self._calendars = _parse_calendars(calendars)
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._days_ahead = days_ahead
        self._days_behind = days_behind
        self._items_synced = 0
        self._last_sync: Optional[datetime] = None

    def _settings(self) -> _CalDAVSettings:
        """Resolve settings from exactly one source: args, env, then file.

        Sources are never mixed field by field, so a URL from one place can
        never receive a password stored in another.
        """
        if self._url:
            source: Dict[str, Any] = {
                "url": self._url,
                "username": self._username,
                "password": self._password,
                "calendars": self._calendars,
            }
        elif os.environ.get(_ENV_URL, "").strip():
            source = {
                "url": os.environ.get(_ENV_URL, ""),
                "username": os.environ.get(_ENV_USERNAME, ""),
                "password": os.environ.get(_ENV_PASSWORD, ""),
                "calendars": os.environ.get(_ENV_CALENDARS, ""),
            }
        else:
            source = load_tokens(self._config_path) or {}

        return _CalDAVSettings(
            url=str(source.get("url") or "").strip(),
            username=str(source.get("username") or "").strip(),
            password=str(source.get("password") or "").strip(),
            calendars=self._calendars or _parse_calendars(source.get("calendars")),
        )

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        return self._settings().complete

    def disconnect(self) -> None:
        self._url = self._username = self._password = ""
        self._calendars = ()
        delete_tokens(self._config_path)

    def connect_with_credentials(
        self,
        url: str,
        username: str,
        password: str,
        *,
        calendars: Optional[Sequence[str]] = None,
    ) -> None:
        """Validate the credentials against the server, then persist them."""
        settings = _CalDAVSettings(
            url=url.strip(),
            username=username.strip(),
            password=password.strip(),
            calendars=_parse_calendars(calendars),
        )
        if not settings.complete:
            raise ValueError("CalDAV URL, username and password are required")
        _validate_url(settings.url)

        _caldav_validate(settings)

        save_tokens(
            self._config_path,
            {
                "url": settings.url,
                "username": settings.username,
                "password": settings.password,
                "calendars": list(settings.calendars),
            },
        )
        self._url = settings.url
        self._username = settings.username
        self._password = settings.password
        self._calendars = settings.calendars

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        """Yield one :class:`Document` per event occurrence, earliest first.

        The window starts at *since* (default: ``days_behind`` days ago) and
        ends ``days_ahead`` days from now.  *cursor* is unused: CalDAV time
        range queries are cheap enough to re-run in full.
        """
        settings = self._settings()
        if not settings.complete:
            return
        _validate_url(settings.url)

        now = datetime.now(tz=timezone.utc)
        if since is None:
            start = now - timedelta(days=self._days_behind)
        else:
            start = since if since.tzinfo else since.astimezone()
        end = now + timedelta(days=self._days_ahead)

        events = sorted(
            (
                e
                for e in _caldav_fetch_events(settings, start, end)
                if not _is_cancelled(e)
            ),
            key=lambda event: _sort_key(event, now),
        )

        synced = 0
        for event in events:
            synced += 1
            yield _event_to_document(event)

        self._items_synced = synced
        self._last_sync = datetime.now(tz=timezone.utc)

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            last_sync=self._last_sync,
        )


__all__ = ["CalDAVConnector"]
