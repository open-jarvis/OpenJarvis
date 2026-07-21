"""Gmail IMAP connector — reads email via IMAP with app password.

Simpler alternative to the OAuth-based Gmail connector.
Uses Python's built-in imaplib + email modules (no dependencies).

Setup: generate an app password at https://myaccount.google.com/apppasswords
"""

from __future__ import annotations

import email as email_lib
import imaplib
import logging
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from imaplib import IMAP4
from typing import Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import delete_tokens, load_tokens, save_tokens
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "gmail_imap.json")


def _decode_header(raw: object) -> str:
    """Decode an email header (str or Header) to a safe plain string.

    Real mail can carry raw 8-bit bytes in headers, which makes ``msg.get()``
    return an ``email.header.Header`` (not JSON serializable) and yields bogus
    charsets like ``unknown-8bit``. Coerce to a string, replacing what can't be
    decoded.
    """
    if not raw:
        return ""
    out = []
    for part, enc in decode_header(raw if isinstance(raw, str) else str(raw)):
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out)


def _extract_text_body(msg: email_lib.message.Message) -> str:
    """Extract plain-text body from an email Message object."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        # Fallback: try text/html
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode("utf-8", errors="replace")
    return ""


def _parse_date(msg: email_lib.message.Message) -> datetime:
    """Parse the Date header, falling back to now."""
    date_str = msg.get("Date", "")
    if not date_str:
        return datetime.now()
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now()


@ConnectorRegistry.register("gmail_imap")
class GmailIMAPConnector(BaseConnector):
    """Gmail connector using IMAP + app password.

    No OAuth needed — just an email address and app password.
    """

    connector_id = "gmail_imap"
    display_name = "Gmail (IMAP)"
    auth_type = "oauth"  # Reuses credential storage pattern
    _default_imap_host = "imap.gmail.com"

    def __init__(
        self,
        email_address: str = "",
        app_password: str = "",
        credentials_path: str = "",
        *,
        imap_host: str = "",
        max_messages: Optional[int] = None,
    ) -> None:
        self._email = email_address
        self._password = app_password
        self._credentials_path = credentials_path or _DEFAULT_CREDENTIALS_PATH
        self._imap_host = imap_host or self._default_imap_host
        # ``None`` means "no cap" — the full inbox is indexed. A positive
        # value is still honored for tests that want a bounded scan.
        self._max_messages = max_messages
        self._items_synced = 0
        self._items_total = 0

    def _resolve_credentials(self) -> tuple[str, str]:
        """Return (email, password) — direct args take priority."""
        if self._email and self._password:
            return self._email, self._password
        tokens = load_tokens(self._credentials_path)
        if tokens:
            return tokens.get("email", ""), tokens.get("password", "")
        return "", ""

    def is_connected(self) -> bool:
        em, pw = self._resolve_credentials()
        return bool(em and pw)

    def disconnect(self) -> None:
        self._email = ""
        self._password = ""
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        return "https://myaccount.google.com/apppasswords"

    def handle_callback(self, code: str) -> None:
        # code format: "email:password"
        if ":" in code:
            em, pw = code.split(":", 1)
            save_tokens(
                self._credentials_path,
                {"email": em.strip(), "password": pw.strip()},
            )
        else:
            save_tokens(
                self._credentials_path,
                {"email": "", "password": code.strip()},
            )

    def _open_imap(self) -> "imaplib.IMAP4_SSL":
        """Open an authenticated, INBOX-selected IMAP connection."""
        em, pw = self._resolve_credentials()
        imap = imaplib.IMAP4_SSL(self._imap_host)
        imap.login(em, pw)
        imap.select("INBOX", readonly=True)
        return imap

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        em, pw = self._resolve_credentials()
        if not em or not pw:
            return

        try:
            imap = self._open_imap()
        except (IMAP4.error, OSError) as exc:
            logger.error("IMAP login failed: %s", exc)
            return

        # Always SEARCH ALL. IMAP has no native cursor that survives a
        # server restart, so applying the SyncEngine's ``since`` filter
        # during a partial backfill would silently skip the older
        # unprocessed messages. The pipeline-level dedup (_seen_doc_ids
        # set + INSERT OR IGNORE in KnowledgeStore) makes re-scanning
        # already-indexed messages cheap, so resume is correct as long
        # as we keep enumerating the full inbox.
        _, data = imap.search(None, "ALL")
        msg_ids = data[0].split()
        self._items_total = len(msg_ids)

        # Newest-first iteration so Deep Research becomes useful while
        # the long tail of older mail finishes indexing in the
        # background. IMAP returns sequence numbers in arrival order
        # (oldest -> newest), so reversing puts the most recent first.
        ordered = list(reversed(msg_ids))
        if self._max_messages is not None and self._max_messages > 0:
            ordered = ordered[: self._max_messages]
        synced = 0

        # A dropped TLS connection mid-backfill (e.g. "[SSL: BAD_LENGTH]") is
        # transient. Reconnect and retry the message instead of aborting the
        # whole sync, so a large inbox finishes without manual "Retry Sync".
        # OSError covers ssl.SSLError and socket errors; IMAP4.abort is raised
        # when the server drops the connection.
        max_reconnects = 5
        consecutive_reconnects = 0
        index = 0
        while index < len(ordered):
            mid = ordered[index]
            try:
                _, msg_data = imap.fetch(mid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
            except (IMAP4.abort, OSError) as exc:
                if consecutive_reconnects >= max_reconnects:
                    logger.error(
                        "IMAP sync stopping after %d reconnect attempts: %s",
                        consecutive_reconnects,
                        exc,
                    )
                    break
                consecutive_reconnects += 1
                logger.warning(
                    "IMAP connection dropped (%s); reconnecting %d/%d",
                    exc,
                    consecutive_reconnects,
                    max_reconnects,
                )
                try:
                    imap.logout()
                except Exception:
                    pass
                try:
                    imap = self._open_imap()
                except (IMAP4.error, OSError) as reconnect_exc:
                    logger.error("IMAP reconnect failed: %s", reconnect_exc)
                    break
                continue
            except Exception:
                index += 1
                continue

            subject = _decode_header(msg.get("Subject", ""))
            sender = _decode_header(msg.get("From", ""))
            to = _decode_header(msg.get("To", ""))
            body = _extract_text_body(msg)
            timestamp = _parse_date(msg)
            message_id = str(msg.get("Message-ID", mid.decode()))

            synced += 1
            index += 1
            consecutive_reconnects = 0
            yield Document(
                doc_id=f"gmail:{message_id}",
                source="gmail",
                doc_type="email",
                content=body,
                title=subject,
                author=sender,
                participants=[a.strip() for a in (to or "").split(",") if a.strip()],
                timestamp=timestamp,
                thread_id=_decode_header(msg.get("In-Reply-To", "")),
                url="https://mail.google.com/mail/u/0/#inbox",
                metadata={
                    "message_id": message_id,
                },
            )

        try:
            imap.logout()
        except Exception:
            pass
        self._items_synced = synced

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
        )

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="gmail_search_emails",
                description="Search Gmail messages by keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                    },
                    "required": ["query"],
                },
                category="communication",
            ),
            ToolSpec(
                name="gmail_list_unread",
                description="List recent unread emails.",
                parameters={
                    "type": "object",
                    "properties": {
                        "max_results": {
                            "type": "integer",
                            "description": "Max results",
                            "default": 10,
                        },
                    },
                },
                category="communication",
            ),
        ]
