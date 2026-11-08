"""MessengerChannel — Facebook Messenger adapter via pymessenger."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from friday_ai.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelStatus,
)
from friday_ai.core.events import EventBus, EventType
from friday_ai.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)


@ChannelRegistry.register("messenger")
class MessengerChannel(BaseChannel):
    """Facebook Messenger channel adapter.

    Uses the Messenger Platform Send API via ``pymessenger``.

    Parameters
    ----------
    access_token:
        Facebook page access token.  Falls back to ``MESSENGER_ACCESS_TOKEN``
        env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "messenger"

    def __init__(
        self,
        access_token: str = "",
        *,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._access_token = access_token or os.environ.get(
            "MESSENGER_ACCESS_TOKEN", ""
        )
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        if not self._access_token:
            logger.warning("No Messenger access_token configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import pymessenger  # noqa: F401
        except ImportError:
            raise ImportError(
                "pymessenger not installed. Install with: "
                "uv sync --extra channel-messenger"
            )
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
        """Send a message to a Messenger user.

        Parameters
        ----------
        channel:
            Facebook user PSID to send to.
        content:
            Text message content.
        """
        if not self._access_token:
            logger.warning("Cannot send: no Messenger credentials configured")
            return False

        try:
            from pymessenger import Bot

            bot = Bot(self._access_token)
            bot.send_text_message(channel, content)

            self._publish_sent(channel, content, conversation_id)
            return True
        except ImportError:
            logger.debug("pymessenger not installed")
            return False
        except Exception:
            logger.debug("Messenger send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["messenger"]

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


__all__ = ["MessengerChannel"]
