"""Apple Mail connector — reads ``.emlx`` files from the macOS Mail.app store.

No network, no credentials. Mail.app keeps every synced message as one
``.emlx`` file under ``~/Library/Mail/V<N>/<account-uuid>/<Mailbox>.mbox/``.
This connector walks a folder of that store and yields one
:class:`Document` per message. It is the only way to index a mailbox whose
provider blocks IMAP (Microsoft 365 tenants with basic auth disabled, for
example) but which Mail.app can still sync.

The path given at connect time may be the whole store (``~/Library/Mail``),
a single account folder, or a single ``.mbox`` folder. Requires **Full Disk
Access** for the process reading the store.

``.emlx`` layout::

    <decimal byte count>\\n<RFC822 message><XML plist trailer>

The byte count covers the RFC822 section only. The trailer plist carries
``date-received`` (Unix epoch), ``flags``, ``remote-id`` and
``conversation-id``. ``.partial.emlx`` files are messages Mail.app has not
fully downloaded (typically attachments missing); their text is still indexed.
"""

from __future__ import annotations

import email as email_lib
import plistlib
from datetime import datetime, timezone
from email import policy
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.gmail_imap import (
    _decode_header,
    _extract_text_body,
    _parse_date,
)
from openjarvis.core.registry import ConnectorRegistry


class EmlxParseError(ValueError):
    """Raised when a ``.emlx`` file does not match the expected layout."""


def parse_emlx(path: Path) -> Tuple[bytes, Dict[str, Any]]:
    """Return ``(rfc822_bytes, plist_dict)`` for one ``.emlx`` file."""
    raw = path.read_bytes()
    newline = raw.find(b"\n")
    if newline == -1:
        raise EmlxParseError(f"{path}: no newline after size header")
    try:
        size = int(raw[:newline].strip())
    except ValueError as exc:
        raise EmlxParseError(f"{path}: invalid size header") from exc
    body_start = newline + 1
    rfc822 = raw[body_start : body_start + size]
    trailer = raw[body_start + size :]
    if not trailer.strip():
        return rfc822, {}
    try:
        plist = plistlib.loads(trailer)
    except Exception as exc:  # noqa: BLE001
        raise EmlxParseError(f"{path}: trailer is not a valid plist") from exc
    return rfc822, plist


def _split_address_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _locate(path: Path) -> Tuple[str, str]:
    """Return ``(account_id, mailbox)`` for an ``.emlx`` path.

    ``account_id`` is the UUID folder under ``V<N>``; ``mailbox`` is the
    ``.mbox`` chain relative to it (nested mailboxes joined with ``/``).
    Falls back to empty strings when the file lives outside a Mail store.
    """
    parts = path.parts
    account_id = ""
    for index, part in enumerate(parts):
        if part.startswith("V") and part[1:].isdigit() and index + 1 < len(parts):
            account_id = parts[index + 1]
            break
    mailbox = "/".join(p[: -len(".mbox")] for p in parts if p.endswith(".mbox"))
    return account_id, mailbox


@ConnectorRegistry.register("apple_mail")
class AppleMailConnector(BaseConnector):
    """Connector that reads messages from the local Mail.app ``.emlx`` store.

    Parameters
    ----------
    mailbox_path:
        Folder to index: the whole store, one account folder, or one
        ``.mbox``. Empty means "not yet configured".
    """

    connector_id = "apple_mail"
    display_name = "Apple Mail"
    auth_type = "filesystem"

    def __init__(self, mailbox_path: str = "") -> None:
        self._vault_path: str = mailbox_path
        self._connected: bool = bool(mailbox_path) and Path(mailbox_path).is_dir()
        self._items_synced: int = 0
        self._items_total: int = 0
        self._last_sync: Optional[datetime] = None

    @property
    def mailbox_path(self) -> str:
        return self._vault_path

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        return bool(self._vault_path) and Path(self._vault_path).is_dir()

    def disconnect(self) -> None:
        self._vault_path = ""
        self._connected = False

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,  # noqa: ARG002
    ) -> Iterator[Document]:
        """Walk the configured folder and yield one :class:`Document` per message.

        ``since`` is compared against the ``date-received`` trailer value
        (falling back to the ``Date`` header), so incremental syncs pick up
        messages Mail.app downloaded after the last run.
        """
        root = Path(self._vault_path).expanduser() if self._vault_path else None
        if root is None or not root.is_dir():
            return

        since_utc: Optional[datetime] = None
        if since is not None:
            since_utc = since if since.tzinfo else since.replace(tzinfo=timezone.utc)

        paths = sorted(p for p in root.rglob("*.emlx") if "MailData" not in p.parts)
        self._items_total = len(paths)
        synced = 0

        for path in paths:
            try:
                rfc822, plist = parse_emlx(path)
            except (EmlxParseError, OSError):
                continue

            msg = email_lib.message_from_bytes(rfc822, policy=policy.compat32)
            received = plist.get("date-received")
            if isinstance(received, (int, float)) and received > 0:
                timestamp = datetime.fromtimestamp(received, tz=timezone.utc)
            else:
                timestamp = _parse_date(msg)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)

            if since_utc is not None and timestamp < since_utc:
                continue

            account_id, mailbox = _locate(path)
            uid = path.name.split(".", 1)[0]
            message_id = _decode_header(msg.get("Message-ID", "")).strip()
            source_id = message_id or f"{account_id}:{mailbox}:{uid}"
            subject = _decode_header(msg.get("Subject", ""))
            sender = _decode_header(msg.get("From", ""))
            recipients = _split_address_list(
                _decode_header(msg.get("To", ""))
            ) + _split_address_list(_decode_header(msg.get("Cc", "")))

            synced += 1
            yield Document(
                doc_id=f"apple_mail:{source_id}",
                source="apple_mail",
                doc_type="email",
                content=_extract_text_body(msg),
                title=subject,
                author=sender,
                participants=recipients,
                timestamp=timestamp,
                thread_id=_decode_header(msg.get("In-Reply-To", "")) or None,
                metadata={
                    "message_id": message_id,
                    "account_id": account_id,
                    "mailbox": mailbox,
                    "emlx_uid": uid,
                    "partial": path.name.endswith(".partial.emlx"),
                    "path": str(path),
                },
                source_id=source_id,
                participants_raw=recipients,
                channel=mailbox or None,
            )

        self._items_synced = synced
        self._last_sync = datetime.now(tz=timezone.utc)

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
            last_sync=self._last_sync,
        )
