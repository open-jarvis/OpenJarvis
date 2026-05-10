"""Strato mail connector using C3PO's Windows Credential Manager entries."""

from __future__ import annotations

import email as email_lib
import imaplib
import logging
import ssl
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Iterator, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry

logger = logging.getLogger(__name__)

_KEYRING_SERVICE = "C3PO-Mail"


def _decode_header_value(raw: str) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded: list[str] = []
    for part, enc in parts:
        if isinstance(part, bytes):
            try:
                decoded.append(part.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                decoded.append(part.decode("utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_text_body(msg: email_lib.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() != "text/plain":
                continue
            payload = part.get_payload(decode=True)
            if payload:
                return payload.decode(
                    part.get_content_charset() or "utf-8",
                    errors="replace",
                )
        return ""

    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return ""


def _parse_date(msg: email_lib.message.Message) -> datetime:
    try:
        return parsedate_to_datetime(msg.get("Date", ""))
    except Exception:
        return datetime.now()


def _strip_port(host: str) -> str:
    return host.split(":", 1)[0] if ":" in host else host


@ConnectorRegistry.register("strato_mail")
class StratoMailConnector(BaseConnector):
    """Read recent Strato inbox messages from C3PO's stored credentials."""

    connector_id = "strato_mail"
    display_name = "Strato Mail"
    auth_type = "local"

    def __init__(
        self,
        *,
        email_address: str = "",
        password: str = "",
        imap_host: str = "",
        keyring_service: str = _KEYRING_SERVICE,
        max_messages: int = 25,
    ) -> None:
        self._email = email_address
        self._password = password
        self._imap_host = _strip_port(imap_host) if imap_host else ""
        self._keyring_service = keyring_service
        self._max_messages = max_messages
        self._items_synced = 0
        self._items_total = 0
        self._last_sync: Optional[datetime] = None

    def _resolve_credentials(self) -> tuple[str, str, str]:
        if self._email and self._password and self._imap_host:
            return self._email, self._imap_host, self._password

        try:
            import keyring
        except ImportError:
            return "", "", ""

        user = keyring.get_password(self._keyring_service, "default_user") or ""
        if not user:
            return "", "", ""

        host = keyring.get_password(self._keyring_service, f"imap_host:{user}") or ""
        password = keyring.get_password(self._keyring_service, f"imap:{user}") or ""
        if not host or not password:
            return "", "", ""
        return user, _strip_port(host), password

    def is_connected(self) -> bool:
        user, host, password = self._resolve_credentials()
        return bool(user and host and password)

    def disconnect(self) -> None:
        self._email = ""
        self._password = ""
        self._imap_host = ""

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        user, host, password = self._resolve_credentials()
        if not user or not host or not password:
            return

        conn = imaplib.IMAP4_SSL(host, 993, ssl_context=ssl.create_default_context())
        try:
            conn.login(user, password)
            conn.select("INBOX", readonly=True)

            if since:
                criterion = f"SINCE {since.strftime('%d-%b-%Y')}"
            else:
                criterion = "ALL"

            typ, data = conn.search(None, criterion)
            if typ != "OK" or not data or not data[0]:
                return

            msg_ids = data[0].split()
            self._items_total = len(msg_ids)
            recent_ids = list(reversed(msg_ids[-self._max_messages :]))

            for msg_id in recent_ids:
                try:
                    typ, msg_data = conn.fetch(msg_id, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    msg = email_lib.message_from_bytes(raw)
                except Exception as exc:
                    logger.debug("Failed to fetch Strato mail %r: %s", msg_id, exc)
                    continue

                subject = _decode_header_value(msg.get("Subject", ""))
                sender = _decode_header_value(msg.get("From", ""))
                to = msg.get("To", "")
                body = _extract_text_body(msg)
                timestamp = _parse_date(msg)
                message_id = msg.get("Message-ID") or msg_id.decode(
                    "ascii",
                    errors="replace",
                )

                self._items_synced += 1
                self._last_sync = datetime.now()
                yield Document(
                    doc_id=f"strato_mail:{message_id}",
                    source="strato_mail",
                    doc_type="email",
                    content=body[:2000],
                    title=subject or "(kein Betreff)",
                    author=sender,
                    participants=[
                        item.strip() for item in (to or "").split(",") if item.strip()
                    ],
                    timestamp=timestamp,
                    thread_id=msg.get("In-Reply-To", ""),
                    metadata={
                        "account": user,
                        "message_id": message_id,
                    },
                )
        except imaplib.IMAP4.error as exc:
            logger.error("Strato IMAP error: %s", exc)
            return
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
            last_sync=self._last_sync,
        )
