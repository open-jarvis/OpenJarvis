"""WhatsApp chat export connector.

Reads WhatsApp chat history from exported .txt files.  WhatsApp allows
exporting individual chats via *Chat → More → Export Chat* on iOS/Android,
producing plain-text files in a well-known format.

Export line format::

    1/15/24, 10:30 AM - Alice: Hey, how are you?
    1/15/24, 10:31 AM - Bob: Good thanks! Working on the project.

Each .txt file in the configured directory is parsed and yielded as a
single :class:`~openjarvis.connectors._stubs.Document` with ``doc_type``
``"message"`` and the message lines joined as content.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Export line regex
# ---------------------------------------------------------------------------

# Matches lines of the form:
#   1/15/24, 10:30 AM - Sender: Message text
#   12/31/2024, 9:05 PM - Alice: Some message
_LINE_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s*[APap][Mm])\s*-\s*(.+?):\s*(.+)$"
)

# Date formats tried in order.  WhatsApp varies by locale/OS version.
_DATE_FORMATS = [
    "%m/%d/%y, %I:%M %p",  # 1/15/24, 10:30 AM
    "%m/%d/%Y, %I:%M %p",  # 1/15/2024, 10:30 AM
    "%d/%m/%y, %I:%M %p",  # 15/1/24, 10:30 AM  (some locales)
    "%d/%m/%Y, %I:%M %p",  # 15/1/2024, 10:30 AM
]


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Try to parse a WhatsApp timestamp string into a UTC-aware datetime."""
    # Normalise whitespace in AM/PM (the regex allows optional space)
    ts_str = ts_str.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(ts_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.debug("Could not parse WhatsApp timestamp: %r", ts_str)
    return None


# ---------------------------------------------------------------------------
# WhatsAppConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("whatsapp")
class WhatsAppConnector(BaseConnector):
    """Read WhatsApp message history from exported .txt files.

    WhatsApp allows exporting individual chats as plain-text files via
    *Chat → More → Export Chat*.  Point this connector at the directory
    containing those files (one file per chat) and it will parse each file
    into a :class:`~openjarvis.connectors._stubs.Document`.

    Parameters
    ----------
    export_path:
        Path to the directory containing WhatsApp export .txt files.
        If empty, no documents are yielded.
    """

    connector_id = "whatsapp"
    display_name = "WhatsApp"
    auth_type = "filesystem"

    def __init__(self, export_path: str = "") -> None:
        self._export_path = Path(export_path) if export_path else Path("")
        self._items_synced: int = 0
        self._items_total: int = 0
        self._last_sync: Optional[datetime] = None

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` if the export directory exists and contains .txt files."""
        if not self._export_path or not self._export_path.is_dir():
            return False
        return any(self._export_path.glob("*.txt"))

    def disconnect(self) -> None:
        """No-op: filesystem connector has nothing to disconnect."""

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,  # noqa: ARG002
    ) -> Iterator[Document]:
        """Parse WhatsApp export files and yield one Document per chat file.

        Parameters
        ----------
        since:
            If provided, skip files (chats) whose most recent message is
            before this datetime.  A file is included if *any* of its
            messages are on or after *since*.
        cursor:
            Not used (included for API compatibility).

        Yields
        ------
        Document
            One document per .txt export file.  The document content is the
            full parsed text of the chat with timestamp and sender prefixes.
            Participants are extracted from the set of senders found.
        """
        if not self._export_path or not self._export_path.is_dir():
            return

        txt_files = sorted(self._export_path.glob("*.txt"))
        self._items_total = len(txt_files)
        synced = 0

        since_utc: Optional[datetime] = None
        if since is not None:
            if since.tzinfo is None:
                since_utc = since.replace(tzinfo=timezone.utc)
            else:
                since_utc = since

        for txt_file in txt_files:
            doc = self._parse_export_file(txt_file, since=since_utc)
            if doc is not None:
                synced += 1
                yield doc

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
        """Expose two MCP tool specs for real-time WhatsApp queries."""
        return [
            ToolSpec(
                name="whatsapp_search_messages",
                description=(
                    "Search WhatsApp messages by keyword or sender name. "
                    "Returns matching messages with sender and timestamp."
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
                            "description": "Maximum number of messages to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="knowledge",
            ),
            ToolSpec(
                name="whatsapp_get_chat",
                description=(
                    "Retrieve the full message history for a specific WhatsApp chat "
                    "by chat name (the export filename without the .txt extension)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "chat_name": {
                            "type": "string",
                            "description": (
                                "Name of the chat (matches the .txt filename, "
                                "e.g. 'WhatsApp Chat with Alice')"
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of messages to return",
                            "default": 50,
                        },
                    },
                    "required": ["chat_name"],
                },
                category="knowledge",
            ),
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_export_file(
        self, path: Path, *, since: Optional[datetime] = None
    ) -> Optional[Document]:
        """Parse a single WhatsApp export .txt file.

        Returns a :class:`Document` if the file contains parseable messages
        that are on or after *since*, or ``None`` if it should be skipped.
        """
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning("Could not read WhatsApp export file: %s", path)
            return None

        chat_name = path.stem
        lines: List[str] = []
        participants: set[str] = set()
        latest_ts: Optional[datetime] = None
        earliest_ts: Optional[datetime] = None

        for raw_line in raw.splitlines():
            m = _LINE_RE.match(raw_line.strip())
            if not m:
                # System message or continuation line — append to previous
                if lines:
                    lines[-1] = lines[-1] + " " + raw_line.strip()
                continue

            ts_str, sender, text = m.group(1), m.group(2), m.group(3)
            dt = _parse_timestamp(ts_str)

            participants.add(sender)

            if dt is not None:
                if earliest_ts is None or dt < earliest_ts:
                    earliest_ts = dt
                if latest_ts is None or dt > latest_ts:
                    latest_ts = dt

            # Format: "[timestamp] Sender: message"
            ts_label = dt.strftime("%Y-%m-%d %H:%M") if dt else ts_str
            lines.append(f"[{ts_label}] {sender}: {text}")

        if not lines:
            return None

        # Apply since filter: skip the whole chat if the latest message
        # predates the since threshold.
        if since is not None and latest_ts is not None and latest_ts < since:
            return None

        content = "\n".join(lines)
        doc_id = f"whatsapp:{hashlib.sha1(path.name.encode()).hexdigest()[:16]}"

        return Document(
            doc_id=doc_id,
            source="whatsapp",
            doc_type="message",
            content=content,
            title=chat_name,
            participants=sorted(participants),
            timestamp=earliest_ts or datetime.now(tz=timezone.utc),
            metadata={
                "chat_name": chat_name,
                "export_file": str(path),
                "message_count": len(lines),
            },
        )


__all__ = ["WhatsAppConnector"]
