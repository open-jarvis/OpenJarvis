"""Gmail IMAP connector — reads email via IMAP with app password.

Simpler alternative to the OAuth-based Gmail connector.
Uses Python's built-in imaplib + email modules (no dependencies).

Setup: generate an app password at https://myaccount.google.com/apppasswords
"""

from __future__ import annotations

import email as email_lib
import imaplib
import logging
import ssl
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
_IMAP_TIMEOUT_SECONDS = 30
_SECURITY_TLS = "tls"
_SECURITY_STARTTLS = "starttls"
_UIDVALIDITY_ATTRIBUTE = "_openjarvis_uidvalidity"


def _normalize_imap_security(value: str) -> str:
    """Normalize an explicit encrypted IMAP transport mode."""
    normalized = (value or _SECURITY_TLS).strip().lower().replace("-", "")
    if normalized in {"tls", "ssl", "implicit", "implicittls"}:
        return _SECURITY_TLS
    if normalized == "starttls":
        return _SECURITY_STARTTLS
    raise ValueError("IMAP security must be 'tls' or 'starttls'")


def _normalize_imap_port(value: object, security: str) -> int:
    """Return a valid port, defaulting from the selected transport mode."""
    if value is None or value == "":
        return 993 if security == _SECURITY_TLS else 143
    if isinstance(value, bool):
        raise ValueError("IMAP port must be an integer between 1 and 65535")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("IMAP port must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("IMAP port must be an integer between 1 and 65535")
    return port


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


def _read_uidvalidity(imap: imaplib.IMAP4) -> str:
    """Read the UID generation for the currently selected mailbox."""
    response_type, data = imap.response("UIDVALIDITY")
    if isinstance(response_type, bytes):
        response_type = response_type.decode("ascii", errors="replace")
    if str(response_type).upper() != "UIDVALIDITY" or not data:
        raise IMAP4.error("IMAP server did not provide UIDVALIDITY")

    raw_value = data[-1]
    if isinstance(raw_value, bytes):
        text = raw_value.decode("ascii", errors="strict").strip()
    else:
        text = str(raw_value).strip()
    try:
        value = int(text)
    except (TypeError, ValueError) as exc:
        raise IMAP4.error("IMAP server provided invalid UIDVALIDITY") from exc
    if value <= 0:
        raise IMAP4.error("IMAP server provided invalid UIDVALIDITY")
    return str(value)


@ConnectorRegistry.register("gmail_imap")
class GmailIMAPConnector(BaseConnector):
    """Gmail connector using IMAP + app password.

    No OAuth needed — just an email address and app password.
    """

    connector_id = "gmail_imap"
    display_name = "Gmail (IMAP)"
    auth_type = "oauth"  # Reuses credential storage pattern
    indexed_sources = ("gmail",)
    _default_imap_host = "imap.gmail.com"

    def __init__(
        self,
        email_address: str = "",
        app_password: str = "",
        credentials_path: str = "",
        *,
        imap_host: str = "",
        imap_port: int | None = None,
        imap_security: str = "",
        max_messages: Optional[int] = None,
    ) -> None:
        self._email = email_address
        self._password = app_password
        self._credentials_path = credentials_path or _DEFAULT_CREDENTIALS_PATH
        self._imap_host = imap_host or self._default_imap_host
        self._imap_port = imap_port
        self._imap_security = imap_security
        # None means "use the persisted validation marker". Direct credentials
        # are not considered connected until a real LOGIN + SELECT succeeds.
        self._credentials_validated: bool | None = None
        # ``None`` means "no cap" — the full inbox is indexed. A positive
        # value is still honored for tests that want a bounded scan.
        self._max_messages = max_messages
        self._items_synced = 0
        self._items_total = 0

    def _resolve_credentials(self) -> tuple[str, str]:
        """Return (email, password) — direct args take priority."""
        email_address, password, _, _, _, _ = self._resolve_connection()
        return email_address, password

    def _host_for_email(self, email_address: str) -> str:
        """Return the connector's provider host for *email_address*."""
        return self._default_imap_host

    def _resolve_connection(self) -> tuple[str, str, str, int, str, bool]:
        """Resolve credentials and transport settings from args or storage."""
        tokens = load_tokens(self._credentials_path) or {}
        using_direct_credentials = bool(self._email and self._password)
        if using_direct_credentials:
            email_address, password = self._email, self._password
            stored_host = ""
            stored_security = ""
            stored_port = None
        else:
            email_address = str(tokens.get("email", ""))
            password = str(tokens.get("password", ""))
            stored_host = str(tokens.get("imap_host", ""))
            stored_security = str(tokens.get("imap_security", ""))
            stored_port = tokens.get("imap_port")

        host = (
            self._imap_host or stored_host or self._host_for_email(email_address)
        ).strip()
        security = _normalize_imap_security(self._imap_security or stored_security)
        port = _normalize_imap_port(
            self._imap_port if self._imap_port is not None else stored_port,
            security,
        )
        if self._credentials_validated is not None:
            validated = self._credentials_validated
        elif using_direct_credentials:
            validated = False
        else:
            validated = tokens.get("validated") is True
        return email_address, password, host, port, security, validated

    def is_connected(self) -> bool:
        em, pw, host, _, _, validated = self._resolve_connection()
        return bool(em and pw and host and validated)

    def disconnect(self) -> None:
        self._email = ""
        self._password = ""
        self._credentials_validated = False
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        return "https://myaccount.google.com/apppasswords"

    def handle_callback(self, code: str) -> None:
        # code format: "email:password"
        if ":" not in code:
            raise ValueError("Expected credentials in 'email:password' format")
        em, pw = code.split(":", 1)
        self.connect_with_credentials(em, pw)

    def connect_with_credentials(
        self,
        email_address: str,
        app_password: str,
        *,
        imap_host: str = "",
        imap_port: int | None = None,
        imap_security: str = "",
    ) -> None:
        """Validate LOGIN + INBOX access, then persist the connection."""
        email_address = email_address.strip()
        app_password = app_password.strip()
        if not email_address or not app_password:
            raise ValueError("Email address and app password are required")

        host = (imap_host or self._host_for_email(email_address)).strip()
        if not host:
            raise ValueError("An IMAP host is required")
        security = _normalize_imap_security(imap_security)
        port = _normalize_imap_port(imap_port, security)

        imap = self._open_authenticated_imap(
            email_address,
            app_password,
            host,
            port,
            security,
        )
        self._close_imap(imap)

        save_tokens(
            self._credentials_path,
            {
                "email": email_address,
                "password": app_password,
                "imap_host": host,
                "imap_port": port,
                "imap_security": security,
                "validated": True,
            },
        )
        self._email = email_address
        self._password = app_password
        self._imap_host = host
        self._imap_port = port
        self._imap_security = security
        self._credentials_validated = True

    def _make_imap_client(self, host: str, port: int, security: str) -> imaplib.IMAP4:
        """Create a TLS or STARTTLS IMAP client."""
        tls_context = ssl.create_default_context()
        if security == _SECURITY_TLS:
            return imaplib.IMAP4_SSL(
                host,
                port,
                ssl_context=tls_context,
                timeout=_IMAP_TIMEOUT_SECONDS,
            )

        imap = imaplib.IMAP4(host, port, timeout=_IMAP_TIMEOUT_SECONDS)
        try:
            status, _ = imap.starttls(ssl_context=tls_context)
            if status != "OK":
                raise IMAP4.error("IMAP server rejected STARTTLS")
            return imap
        except Exception:
            self._close_imap(imap)
            raise

    def _open_authenticated_imap(
        self,
        email_address: str,
        password: str,
        host: str,
        port: int,
        security: str,
    ) -> imaplib.IMAP4:
        """Open, authenticate, and select INBOX on one IMAP connection."""
        imap = self._make_imap_client(host, port, security)
        try:
            status, _ = imap.login(email_address, password)
            if status != "OK":
                raise IMAP4.error("IMAP login rejected")
            status, _ = imap.select("INBOX", readonly=True)
            if status != "OK":
                raise IMAP4.error("Unable to select INBOX read-only")
            # A UID is meaningful only together with this mailbox generation.
            # Store it on the selected connection so reconnects cannot reuse an
            # old UID against a reset or replaced mailbox.
            setattr(imap, _UIDVALIDITY_ATTRIBUTE, _read_uidvalidity(imap))
            return imap
        except Exception:
            self._close_imap(imap)
            raise

    def _open_imap(self) -> imaplib.IMAP4:
        """Open an authenticated, INBOX-selected IMAP connection."""
        em, pw, host, port, security, _ = self._resolve_connection()
        if not em or not pw or not host:
            raise ValueError("Complete IMAP credentials are required")
        imap = self._open_authenticated_imap(em, pw, host, port, security)
        self._credentials_validated = True
        return imap

    @staticmethod
    def _close_imap(imap: imaplib.IMAP4 | None) -> None:
        """Best-effort logout for normal, failed, and cancelled syncs."""
        if imap is None:
            return
        try:
            imap.logout()
        except Exception:
            try:
                imap.shutdown()
            except Exception:
                pass

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
        except (IMAP4.error, OSError, ValueError) as exc:
            if isinstance(exc, (IMAP4.error, ValueError)):
                self._credentials_validated = False
            logger.error("IMAP login failed: %s", exc)
            return

        synced = 0
        try:
            uidvalidity = str(getattr(imap, _UIDVALIDITY_ATTRIBUTE))
            # SEARCH ALL is deliberate: pipeline dedup makes a complete scan
            # safe while avoiding gaps after an interrupted backfill.
            status, data = imap.uid("SEARCH", None, "ALL")
            if status != "OK" or not data or data[0] is None:
                logger.error("IMAP UID SEARCH ALL failed: %s", status)
                return
            message_uids = data[0].split() if data[0] else []
            self._items_total = len(message_uids)
            ordered = list(reversed(message_uids))
            if self._max_messages is not None and self._max_messages > 0:
                ordered = ordered[: self._max_messages]

            max_reconnects = 5
            consecutive_reconnects = 0
            index = 0
            while index < len(ordered):
                message_uid = ordered[index]
                try:
                    status, msg_data = imap.uid("FETCH", message_uid, "(RFC822)")
                    message_record = next(
                        (
                            item
                            for item in msg_data or []
                            if isinstance(item, tuple)
                            and len(item) > 1
                            and isinstance(item[1], bytes)
                        ),
                        None,
                    )
                    if status != "OK" or message_record is None:
                        index += 1
                        continue
                    raw = message_record[1]
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
                    self._close_imap(imap)
                    imap = None
                    try:
                        imap = self._open_imap()
                    except (IMAP4.error, OSError, ValueError) as reconnect_exc:
                        logger.error("IMAP reconnect failed: %s", reconnect_exc)
                        break
                    reconnected_uidvalidity = str(getattr(imap, _UIDVALIDITY_ATTRIBUTE))
                    if reconnected_uidvalidity != uidvalidity:
                        logger.error(
                            "IMAP UIDVALIDITY changed from %s to %s during sync; "
                            "stopping before reusing stale UIDs",
                            uidvalidity,
                            reconnected_uidvalidity,
                        )
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
                uid_text = message_uid.decode("ascii", errors="replace")
                message_id = _decode_header(msg.get("Message-ID", "")) or (
                    f"{uidvalidity}:{uid_text}"
                )

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
                    participants=[
                        address.strip()
                        for address in (to or "").split(",")
                        if address.strip()
                    ],
                    timestamp=timestamp,
                    thread_id=_decode_header(msg.get("In-Reply-To", "")),
                    url="https://mail.google.com/mail/u/0/#inbox",
                    metadata={
                        "message_id": message_id,
                        "imap_uid": uid_text,
                        "imap_uidvalidity": uidvalidity,
                    },
                )
        finally:
            self._close_imap(imap)
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
