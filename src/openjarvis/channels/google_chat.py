"""GoogleChatChannel — Google Chat webhook adapter."""

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


@ChannelRegistry.register("google_chat")
class GoogleChatChannel(BaseChannel):
    """Google Chat webhook channel adapter (send-only).

    Parameters
    ----------
    webhook_url:
        Google Chat incoming webhook URL.  Falls back to
        ``GOOGLE_CHAT_WEBHOOK_URL`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "google_chat"

    def __init__(
        self,
        webhook_url: str = "",
        *,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._webhook_url = webhook_url or os.environ.get(
            "GOOGLE_CHAT_WEBHOOK_URL",
            "",
        )
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Mark as connected (send-only — no persistent connection)."""
        if not self._webhook_url:
            logger.warning("No Google Chat webhook URL configured")
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
        """Send a message to Google Chat via the configured webhook URL."""
        if not self._webhook_url:
            logger.warning("Cannot send: no Google Chat webhook URL configured")
            return False

        try:
            import httpx

            payload: Dict[str, Any] = {"text": content}

            resp = httpx.post(
                self._webhook_url,
                json=payload,
                timeout=10.0,
            )
            if resp.status_code < 300:
                self._publish_sent(channel, content, conversation_id)
                return True
            logger.warning(
                "Google Chat API returned status %d",
                resp.status_code,
            )
            return False
        except Exception:
            logger.debug("Google Chat send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["google_chat"]

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


__all__ = ["GoogleChatChannel"]
