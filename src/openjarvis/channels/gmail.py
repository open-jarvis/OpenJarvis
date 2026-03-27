"""GmailChannel — native Gmail API adapter using OAuth2."""

from __future__ import annotations

import base64
import logging
import os
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


@ChannelRegistry.register("gmail")
class GmailChannel(BaseChannel):
    """Native Gmail channel adapter using the Gmail API with OAuth2.

    Parameters
    ----------
    credentials_path:
        Path to the OAuth2 ``credentials.json`` file.
        Falls back to ``GMAIL_CREDENTIALS_PATH`` env var.
    token_path:
        Path to the stored OAuth2 token file.
        Falls back to ``GMAIL_TOKEN_PATH`` env var.
    user_id:
        Gmail user ID (default ``"me"`` for the authenticated user).
    poll_interval:
        Seconds between inbox polls (default 30).
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "gmail"

    def __init__(
        self,
        credentials_path: str = "",
        *,
        token_path: str = "",
        user_id: str = "me",
        poll_interval: int = 30,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._credentials_path = credentials_path or os.environ.get(
            "GMAIL_CREDENTIALS_PATH", "",
        )
        self._token_path = token_path or os.environ.get(
            "GMAIL_TOKEN_PATH", "",
        )
        self._user_id = user_id
        self._poll_interval = poll_interval
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._service: Any = None
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Load OAuth2 credentials and build the Gmail API service."""
        if not self._credentials_path and not self._token_path:
            logger.warning("No Gmail credentials configured")
            self._status = ChannelStatus.ERROR
            return

        self._stop_event.clear()
        self._status = ChannelStatus.CONNECTING

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

            creds: Any = None
            if self._token_path and os.path.exists(self._token_path):
                creds = Credentials.from_authorized_user_file(
                    self._token_path, SCOPES,
                )

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    from google.auth.transport.requests import Request

                    creds.refresh(Request())
                elif self._credentials_path and os.path.exists(
                    self._credentials_path,
                ):
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self._credentials_path, SCOPES,
                    )
                    creds = flow.run_local_server(port=0)
                else:
                    logger.warning("Gmail credentials not found or invalid")
                    self._status = ChannelStatus.ERROR
                    return

                # Save token for future use
                if self._token_path and creds:
                    with open(self._token_path, "w") as token_file:
                        token_file.write(creds.to_json())

            self._service = build("gmail", "v1", credentials=creds)
            self._status = ChannelStatus.CONNECTED
            logger.info("Gmail channel connected")

            # Start polling thread
            self._listener_thread = threading.Thread(
                target=self._poll_loop, daemon=True,
            )
            self._listener_thread.start()
        except ImportError:
            logger.warning(
                "Google API libraries not installed; "
                "install with: pip install openjarvis[channel-gmail]",
            )
            self._status = ChannelStatus.ERROR
        except Exception:
            logger.debug("Gmail connect failed", exc_info=True)
            self._status = ChannelStatus.ERROR

    def disconnect(self) -> None:
        """Stop the polling thread and clear the service."""
        self._stop_event.set()
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=5.0)
            self._listener_thread = None
        self._service = None
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
        """Send an email via the Gmail API.

        ``channel`` is the recipient email address.
        """
        if self._service is None:
            logger.warning("Cannot send: Gmail service not connected")
            return False

        try:
            msg = MIMEText(content)
            msg["To"] = channel
            msg["From"] = self._user_id
            msg["Subject"] = (metadata or {}).get(
                "subject", "Message from OpenJarvis",
            )

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            body: Dict[str, Any] = {"raw": raw}
            if conversation_id:
                body["threadId"] = conversation_id

            self._service.users().messages().send(
                userId=self._user_id, body=body,
            ).execute()

            self._publish_sent(channel, content, conversation_id)
            return True
        except Exception:
            logger.debug("Gmail send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        if self._status == ChannelStatus.CONNECTED and self._service is None:
            return ChannelStatus.ERROR
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["inbox"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming Gmail messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

    def _poll_loop(self) -> None:
        """Poll Gmail inbox for unread messages."""
        while not self._stop_event.is_set():
            try:
                if self._service is None:
                    break

                results = (
                    self._service.users()
                    .messages()
                    .list(userId=self._user_id, q="is:unread")
                    .execute()
                )
                messages = results.get("messages", [])

                for msg_ref in messages:
                    msg_id = msg_ref["id"]
                    msg = (
                        self._service.users()
                        .messages()
                        .get(userId=self._user_id, id=msg_id, format="full")
                        .execute()
                    )

                    headers = {
                        h["name"]: h["value"]
                        for h in msg.get("payload", {}).get("headers", [])
                    }

                    # Extract body text
                    body = ""
                    payload = msg.get("payload", {})
                    if payload.get("body", {}).get("data"):
                        body = base64.urlsafe_b64decode(
                            payload["body"]["data"],
                        ).decode("utf-8", errors="replace")
                    elif payload.get("parts"):
                        for part in payload["parts"]:
                            if part.get("mimeType") == "text/plain":
                                data = part.get("body", {}).get("data", "")
                                if data:
                                    body = base64.urlsafe_b64decode(
                                        data,
                                    ).decode("utf-8", errors="replace")
                                break

                    cm = ChannelMessage(
                        channel="gmail",
                        sender=headers.get("From", ""),
                        content=body,
                        message_id=msg_id,
                        conversation_id=msg.get("threadId", ""),
                    )

                    for handler in self._handlers:
                        try:
                            handler(cm)
                        except Exception:
                            logger.exception("Gmail handler error")

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

                    # Mark message as read
                    self._service.users().messages().modify(
                        userId=self._user_id,
                        id=msg_id,
                        body={"removeLabelIds": ["UNREAD"]},
                    ).execute()

            except Exception:
                logger.debug("Gmail poll error", exc_info=True)

            self._stop_event.wait(self._poll_interval)

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


__all__ = ["GmailChannel"]
