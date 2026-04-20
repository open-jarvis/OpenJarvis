"""Apple Contacts connector — reads directly from the macOS Contacts SQLite database.

No API calls, no OAuth.  The connector opens
``~/Library/Application Support/AddressBook/AddressBook-v22.abcddb``
in read-only mode and yields one :class:`Document` per contact.

Requires **Full Disk Access** granted to the terminal / app in
System Settings → Privacy & Security → Full Disk Access.

Timestamp notes
---------------
The Contacts database stores timestamps as seconds since the Apple epoch
of 2001-01-01 00:00:00 UTC.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDRESSBOOK_DIR = Path.home() / "Library" / "Application Support" / "AddressBook"

_DEFAULT_DB_PATH = _ADDRESSBOOK_DIR / "AddressBook-v22.abcddb"

_DB_FILENAME = "AddressBook-v22.abcddb"

# Apple epoch: 2001-01-01 00:00:00 UTC
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Apple Contacts stores labels in the format _$!<Label>!$_
_LABEL_PREFIX = "_$!<"
_LABEL_SUFFIX = ">!$_"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apple_ts_to_datetime(apple_seconds: float) -> datetime:
    """Convert an Apple seconds timestamp to a UTC datetime."""
    return _APPLE_EPOCH + timedelta(seconds=apple_seconds)


def _clean_label(raw: str | None) -> str:
    """Strip Apple's internal label markup (``_$!<Work>!$_`` → ``Work``)."""
    if not raw:
        return ""
    if raw.startswith(_LABEL_PREFIX) and raw.endswith(_LABEL_SUFFIX):
        return raw[len(_LABEL_PREFIX) : -len(_LABEL_SUFFIX)]
    return raw


def _build_name(first: str, middle: str, last: str, org: str) -> str:
    """Build a display name from name components."""
    parts = [p for p in (first, middle, last) if p]
    name = " ".join(parts)
    if not name and org:
        return org
    return name


def _format_address(
    street: str, city: str, state: str, zipcode: str, country: str
) -> str:
    """Format a postal address into a single string."""
    line1 = street or ""
    parts2 = [p for p in (city, state) if p]
    line2 = ", ".join(parts2)
    if zipcode:
        line2 = f"{line2} {zipcode}".strip()
    if country:
        line2 = f"{line2}, {country}".strip(", ")
    lines = [part for part in (line1, line2) if part]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SQL queries
# ---------------------------------------------------------------------------

_CONTACTS_QUERY = """\
SELECT r.Z_PK,
       r.ZFIRSTNAME,
       r.ZMIDDLENAME,
       r.ZLASTNAME,
       r.ZORGANIZATION,
       r.ZJOBTITLE,
       r.ZDEPARTMENT,
       r.ZNICKNAME,
       r.ZBIRTHDAY,
       r.ZCREATIONDATE,
       r.ZMODIFICATIONDATE,
       r.ZUNIQUEID
FROM   ZABCDRECORD r
WHERE  r.ZFIRSTNAME IS NOT NULL
   OR  r.ZLASTNAME IS NOT NULL
   OR  r.ZORGANIZATION IS NOT NULL
ORDER BY r.ZMODIFICATIONDATE ASC
"""

_PHONES_QUERY = """\
SELECT ZFULLNUMBER, ZLABEL FROM ZABCDPHONENUMBER WHERE ZOWNER = ?
ORDER BY ZORDERINGINDEX
"""

_EMAILS_QUERY = """\
SELECT ZADDRESS, ZLABEL FROM ZABCDEMAILADDRESS WHERE ZOWNER = ?
ORDER BY ZORDERINGINDEX
"""

_ADDRESSES_QUERY = """\
SELECT ZSTREET, ZCITY, ZSTATE, ZZIPCODE, ZCOUNTRYNAME, ZLABEL
FROM ZABCDPOSTALADDRESS WHERE ZOWNER = ?
ORDER BY ZORDERINGINDEX
"""

_URLS_QUERY = """\
SELECT ZURL, ZLABEL FROM ZABCDURLADDRESS WHERE ZOWNER = ?
ORDER BY ZORDERINGINDEX
"""

_SOCIAL_QUERY = """\
SELECT ZUSERNAME, ZSERVICENAME, ZLABEL FROM ZABCDSOCIALPROFILE WHERE ZOWNER = ?
ORDER BY ZORDERINGINDEX
"""

_NOTES_QUERY = """\
SELECT ZTEXT FROM ZABCDNOTE WHERE ZCONTACT = ?
"""

_SEARCH_QUERY = """\
SELECT r.Z_PK,
       r.ZFIRSTNAME,
       r.ZMIDDLENAME,
       r.ZLASTNAME,
       r.ZORGANIZATION,
       r.ZJOBTITLE,
       r.ZDEPARTMENT,
       r.ZNICKNAME,
       r.ZMODIFICATIONDATE,
       r.ZUNIQUEID
FROM   ZABCDRECORD r
WHERE  (r.ZFIRSTNAME LIKE ? OR r.ZLASTNAME LIKE ?
        OR r.ZORGANIZATION LIKE ? OR r.ZNICKNAME LIKE ?
        OR r.ZJOBTITLE LIKE ?)
LIMIT  ?
"""

# ---------------------------------------------------------------------------
# AppleContactsConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("apple_contacts")
class AppleContactsConnector(BaseConnector):
    """Connector that reads contacts from the macOS Contacts SQLite database.

    Parameters
    ----------
    db_path:
        Path to ``AddressBook-v22.abcddb``.  Defaults to
        ``~/Library/Application Support/AddressBook/AddressBook-v22.abcddb``.
    """

    connector_id = "apple_contacts"
    display_name = "Apple Contacts"
    auth_type = "local"

    def __init__(self, db_path: str = "") -> None:
        self._db_path: Path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._connected: bool = False
        self._items_synced: int = 0
        self._items_total: int = 0
        self._last_sync: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _all_db_paths(self) -> List[Path]:
        """Return paths to all AddressBook databases (main + iCloud sources).

        macOS stores the local address book at the top level and synced
        accounts (iCloud, Exchange, etc.) under ``Sources/<UUID>/``.
        """
        paths: List[Path] = []
        # Main database
        if self._db_path.exists():
            paths.append(self._db_path)
        # Source databases (iCloud, Exchange, etc.)
        sources_dir = self._db_path.parent / "Sources"
        if sources_dir.is_dir():
            for child in sorted(sources_dir.iterdir()):
                candidate = child / _DB_FILENAME
                if candidate.exists():
                    paths.append(candidate)
        return paths

    @staticmethod
    def _open_db(path: Path) -> sqlite3.Connection | None:
        """Open a Contacts database read-only.  Returns None on failure."""
        try:
            return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            return None

    def _build_content(
        self, conn: sqlite3.Connection, pk: int, meta: Dict[str, Any]
    ) -> str:
        """Build a human-readable text block for one contact."""
        lines: List[str] = []

        name = meta.get("name", "")
        if name:
            lines.append(name)

        org = meta.get("organization", "")
        title = meta.get("job_title", "")
        dept = meta.get("department", "")
        if org or title:
            org_parts = [p for p in (title, dept, org) if p]
            lines.append(" — ".join(org_parts))

        nickname = meta.get("nickname", "")
        if nickname:
            lines.append(f"Nickname: {nickname}")

        birthday = meta.get("birthday", "")
        if birthday:
            lines.append(f"Birthday: {birthday}")

        # Phone numbers
        phones = conn.execute(_PHONES_QUERY, (pk,)).fetchall()
        for number, label in phones:
            if number:
                lbl = _clean_label(label)
                prefix = f"{lbl}: " if lbl else ""
                lines.append(f"Phone {prefix}{number}")

        # Email addresses
        emails = conn.execute(_EMAILS_QUERY, (pk,)).fetchall()
        for addr, label in emails:
            if addr:
                lbl = _clean_label(label)
                prefix = f"{lbl}: " if lbl else ""
                lines.append(f"Email {prefix}{addr}")

        # Postal addresses
        addresses = conn.execute(_ADDRESSES_QUERY, (pk,)).fetchall()
        for street, city, state, zipcode, country, label in addresses:
            formatted = _format_address(
                street or "",
                city or "",
                state or "",
                zipcode or "",
                country or "",
            )
            if formatted:
                lbl = _clean_label(label)
                prefix = f"{lbl}: " if lbl else ""
                lines.append(f"Address {prefix}{formatted}")

        # URLs
        urls = conn.execute(_URLS_QUERY, (pk,)).fetchall()
        for url, label in urls:
            if url:
                lbl = _clean_label(label)
                prefix = f"{lbl}: " if lbl else ""
                lines.append(f"URL {prefix}{url}")

        # Social profiles
        socials = conn.execute(_SOCIAL_QUERY, (pk,)).fetchall()
        for username, service, label in socials:
            if username:
                svc = service or _clean_label(label) or ""
                lines.append(f"Social {svc}: {username}")

        # Notes
        notes = conn.execute(_NOTES_QUERY, (pk,)).fetchall()
        for (text,) in notes:
            if text:
                lines.append(f"Notes: {text}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` if any AddressBook database exists."""
        return len(self._all_db_paths()) > 0

    def disconnect(self) -> None:
        """Mark the connector as disconnected."""
        self._connected = False

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,  # noqa: ARG002
    ) -> Iterator[Document]:
        """Read contacts from AddressBook and yield one :class:`Document` each.

        Parameters
        ----------
        since:
            If provided, skip contacts whose modification time is before
            this datetime.
        cursor:
            Not used for this local connector (included for API
            compatibility).

        Yields
        ------
        Document
            One document per contact with all fields as structured text.
        """
        db_paths = self._all_db_paths()
        if not db_paths:
            return

        seen_ids: set[str] = set()
        synced = 0
        total = 0

        for db_path in db_paths:
            conn = self._open_db(db_path)
            if conn is None:
                continue

            try:
                rows = conn.execute(_CONTACTS_QUERY).fetchall()
                total += len(rows)
                self._items_total = total

                for row in rows:
                    pk: int = row[0]
                    first: str = row[1] or ""
                    middle: str = row[2] or ""
                    last: str = row[3] or ""
                    org: str = row[4] or ""
                    job_title: str = row[5] or ""
                    department: str = row[6] or ""
                    nickname: str = row[7] or ""
                    birthday_ts: float | None = row[8]
                    creation_ts: float = row[9] or 0.0
                    mod_ts: float = row[10] or 0.0
                    unique_id: str = row[11] or str(pk)

                    # Deduplicate across sources
                    if unique_id in seen_ids:
                        continue
                    seen_ids.add(unique_id)

                    timestamp = (
                        _apple_ts_to_datetime(mod_ts)
                        if mod_ts
                        else _apple_ts_to_datetime(creation_ts)
                    )

                    # Apply since filter
                    if since is not None:
                        since_utc = since
                        if since_utc.tzinfo is None:
                            since_utc = since_utc.replace(tzinfo=timezone.utc)
                        if timestamp < since_utc:
                            continue

                    name = _build_name(first, middle, last, org)
                    birthday = ""
                    if birthday_ts:
                        try:
                            birthday = _apple_ts_to_datetime(birthday_ts).strftime(
                                "%Y-%m-%d"
                            )
                        except (ValueError, OverflowError):
                            pass

                    meta: Dict[str, Any] = {
                        "name": name,
                        "first_name": first,
                        "last_name": last,
                        "organization": org,
                        "job_title": job_title,
                        "department": department,
                        "nickname": nickname,
                        "birthday": birthday,
                    }

                    content = self._build_content(conn, pk, meta)

                    doc = Document(
                        doc_id=f"apple_contacts:{unique_id}",
                        source="apple_contacts",
                        doc_type="contact",
                        content=content,
                        title=name,
                        author=name,
                        timestamp=timestamp,
                        metadata=meta,
                    )
                    synced += 1
                    yield doc

            finally:
                conn.close()

        self._items_synced = synced
        self._last_sync = datetime.now(tz=timezone.utc)

    def sync_status(self) -> SyncStatus:
        """Return sync progress from the most recent :meth:`sync` call."""
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
            last_sync=self._last_sync,
        )

    # ------------------------------------------------------------------
    # MCP tools
    # ------------------------------------------------------------------

    def mcp_tools(self) -> List[ToolSpec]:
        """Expose MCP tool specs for real-time Apple Contacts queries."""
        return [
            ToolSpec(
                name="contacts_search",
                description=(
                    "Search Apple Contacts by name, organization, or job title. "
                    "Returns matching contacts with full details."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query string",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of contacts to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="knowledge",
            ),
            ToolSpec(
                name="contacts_get_contact",
                description=(
                    "Retrieve full details of an Apple Contact by its "
                    "unique identifier."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": (
                                "Apple Contacts unique identifier (ZUNIQUEID)"
                            ),
                        },
                    },
                    "required": ["contact_id"],
                },
                category="knowledge",
            ),
        ]
