"""WhatsAppChannel — WhatsApp Cloud API adapter."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelStatus,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)


@ChannelRegistry.register("whatsapp")
class WhatsAppChannel(BaseChannel):
    """WhatsApp Cloud API channel adapter (send-only).

    Parameters
    ----------
    access_token:
        WhatsApp Cloud API access token.  Falls back to
        ``WHATSAPP_ACCESS_TOKEN`` env var.
    phone_number_id:
        WhatsApp phone number ID.  Falls back to
        ``WHATSAPP_PHONE_NUMBER_ID`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "whatsapp"

    def __init__(
        self,
        access_token: str = "",
        *,
        phone_number_id: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._token = access_token or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        self._phone_number_id = phone_number_id or os.environ.get(
            "WHATSAPP_PHONE_NUMBER_ID",
            "",
        )
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Mark as connected (send-only — no persistent connection)."""
        if not self._token:
            logger.warning("No WhatsApp access token configured")
            self._status = ChannelStatus.ERROR
            return
        self._status = ChannelStatus.CONNECTED

    def disconnect(self) -> None:
        """Mark as disconnected."""
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
        """Send a message via the WhatsApp Cloud API."""
        if not self._token:
            logger.warning("Cannot send: no WhatsApp access token")
            return False

        try:
            import httpx

            url = f"https://graph.facebook.com/v21.0/{self._phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            }
            payload: Dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": channel,
                "type": "text",
                "text": {"body": content},
            }

            resp = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code < 300:
                self._publish_sent(channel, content, conversation_id)
                return True
            logger.warning(
                "WhatsApp API returned status %d",
                resp.status_code,
            )
            return False
        except Exception:
            logger.debug("WhatsApp send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["whatsapp"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

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


__all__ = ["WhatsAppChannel"]
