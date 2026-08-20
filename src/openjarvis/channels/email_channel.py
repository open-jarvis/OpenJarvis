"""EmailChannel — SMTP/IMAP email adapter (stdlib only, zero extra deps)."""

from __future__ import annotations

import logging
import os
import smtplib
import threading
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)


@ChannelRegistry.register("email")
class EmailChannel(BaseChannel):
    """Email channel adapter using stdlib ``smtplib`` and ``imaplib``.

    Parameters
    ----------
    smtp_host:
        SMTP server hostname.
    smtp_port:
        SMTP server port (default 587 for STARTTLS).
    imap_host:
        IMAP server hostname for incoming messages.
    imap_port:
        IMAP server port (default 993 for SSL).
    username:
        Email username.  Falls back to ``EMAIL_USERNAME`` env var.
    password:
        Email password.  Falls back to ``EMAIL_PASSWORD`` env var.
    use_tls:
        Whether to use TLS (default ``True``).
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "email"

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 587,
        *,
        imap_host: str = "",
        imap_port: int = 993,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._imap_host = imap_host
        self._imap_port = imap_port
        self._username = username or os.environ.get("EMAIL_USERNAME", "")
        self._password = password or os.environ.get("EMAIL_PASSWORD", "")
        self._use_tls = use_tls
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Start IMAP polling for incoming messages (if configured)."""
        if not self._smtp_host or not self._username:
            logger.warning("Email channel not fully configured")
            self._status = ChannelStatus.ERROR
            return

        self._stop_event.clear()
        self._status = ChannelStatus.CONNECTING

        if self._imap_host:
            self._listener_thread = threading.Thread(
                target=self._imap_poll_loop,
                daemon=True,
            )
            self._listener_thread.start()

        self._status = ChannelStatus.CONNECTED
        logger.info("Email channel connected (SMTP: %s)", self._smtp_host)

    def disconnect(self) -> None:
        """Stop the IMAP listener thread."""
        self._stop_event.set()
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=5.0)
            self._listener_thread = None
        self._status = ChannelStatus.DISCONNECTED

    # -- send / receive --------------------------------------------------------

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        """Send an email via SMTP. ``channel`` is the recipient address."""
        if not self._smtp_host or not self._username:
            logger.warning("Cannot send: email not configured")
            return False

        try:
            msg = MIMEText(content)
            msg["From"] = self._username
            msg["To"] = channel
            msg["Subject"] = (metadata or {}).get(
                "subject",
                "Message from OpenJarvis",
            )
            if conversation_id:
                msg["In-Reply-To"] = conversation_id

            if self._use_tls:
                with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                    server.starttls()
                    server.login(self._username, self._password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                    if self._password:
                        server.login(self._username, self._password)
                    server.send_message(msg)

            self._publish_sent(channel, content, conversation_id)
            return True
        except Exception:
            logger.debug("Email send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["email"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming email messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

    def _imap_poll_loop(self) -> None:
        """Poll IMAP INBOX for new messages."""
        import email
        import imaplib

        while not self._stop_event.is_set():
            try:
                if self._use_tls:
                    imap = imaplib.IMAP4_SSL(
                        self._imap_host,
                        self._imap_port,
                    )
                else:
                    imap = imaplib.IMAP4(self._imap_host, self._imap_port)

                imap.login(self._username, self._password)
                imap.select("INBOX")

                _, data = imap.search(None, "UNSEEN")
                for num in data[0].split():
                    _, msg_data = imap.fetch(num, "(RFC822)")
                    if msg_data[0] is None:
                        continue
                    raw = msg_data[0][1]
                    parsed = email.message_from_bytes(raw)
                    body = ""
                    if parsed.is_multipart():
                        for part in parsed.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(
                                    errors="replace",
                                )
                                break
                    else:
                        body = parsed.get_payload(decode=True).decode(
                            errors="replace",
                        )

                    cm = ChannelMessage(
                        channel="email",
                        sender=parsed.get("From", ""),
                        content=body,
                        message_id=parsed.get("Message-ID", ""),
                        conversation_id=parsed.get("In-Reply-To", ""),
                    )
                    for handler in self._handlers:
                        try:
                            handler(cm)
                        except Exception:
                            logger.exception("Email handler error")
                    if self._bus is not None:
                        self._bus.publish(
                            EventType.CHANNEL_MESSAGE_RECEIVED,
                            {
                                "channel": cm.channel,
                                "sender": cm.sender,
                                "content": cm.content,
                                "message_id": cm.message_id,
                            },
                        )

                imap.close()
                imap.logout()
            except Exception:
                logger.debug("IMAP poll error", exc_info=True)

            self._stop_event.wait(30.0)

    def _publish_sent(self, channel: str, content: str, conversation_id: str) -> None:
        """Publish a CHANNEL_MESSAGE_SENT event on the bus."""
        if self._bus is not None:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_SENT,
                {
                    "channel": channel,
                    "content": content,
                    "conversation_id": conversation_id,
                },
            )


__all__ = ["EmailChannel"]
