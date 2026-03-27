"""Twilio SMS channel for sending and receiving text messages."""

from __future__ import annotations

import logging
import os
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


def _create_twilio_client(  # noqa: ANN201
    account_sid: str, auth_token: str
):
    from twilio.rest import Client

    return Client(account_sid, auth_token)


@ChannelRegistry.register("twilio")
class TwilioSMSChannel(BaseChannel):
    """Send and receive SMS via Twilio.

    Sending uses the Twilio REST API.  Receiving is handled by
    the ``/webhooks/twilio`` FastAPI endpoint which calls
    registered handlers.
    """

    channel_id = "twilio"

    def __init__(
        self,
        *,
        account_sid: str = "",
        auth_token: str = "",
        phone_number: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._account_sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID", "")
        self._auth_token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN", "")
        self._phone_number = phone_number or os.environ.get("TWILIO_PHONE_NUMBER", "")
        self._bus = bus
        self._client: Any = None
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    def connect(self) -> None:
        try:
            self._client = _create_twilio_client(self._account_sid, self._auth_token)
            self._status = ChannelStatus.CONNECTED
        except Exception:
            logger.exception("Failed to create Twilio client")
            self._status = ChannelStatus.ERROR

    def disconnect(self) -> None:
        self._client = None
        self._status = ChannelStatus.DISCONNECTED

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        if not self._client:
            logger.error("Twilio client not connected")
            return False
        try:
            self._client.messages.create(
                body=content,
                from_=self._phone_number,
                to=channel,
            )
            self._publish_sent(channel, content, conversation_id)
            return True
        except Exception:
            logger.exception("Failed to send SMS to %s", channel)
            return False

    def status(self) -> ChannelStatus:
        return self._status

    def list_channels(self) -> List[str]:
        return ["twilio"]

    def on_message(self, handler: ChannelHandler) -> None:
        self._handlers.append(handler)

    def handle_webhook(
        self,
        from_number: str,
        body: str,
        message_sid: str = "",
    ) -> None:
        """Called by the webhook route for incoming SMS."""
        msg = ChannelMessage(
            channel="twilio",
            sender=from_number,
            content=body,
            message_id=message_sid,
        )
        for handler in self._handlers:
            handler(msg)
        if self._bus:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_RECEIVED,
                {
                    "channel": "twilio",
                    "sender": from_number,
                    "content": body,
                    "message_id": message_sid,
                },
            )

    def _publish_sent(
        self,
        channel: str,
        content: str,
        conversation_id: str,
    ) -> None:
        if self._bus:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_SENT,
                {
                    "channel": "twilio",
                    "content": content,
                    "conversation_id": conversation_id,
                },
            )
