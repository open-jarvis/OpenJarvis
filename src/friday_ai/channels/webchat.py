"""WebChatChannel — in-memory message queue for webchat/testing."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from friday_ai.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)
from friday_ai.core.events import EventBus, EventType
from friday_ai.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)


@ChannelRegistry.register("webchat")
class WebChatChannel(BaseChannel):
    """In-memory webchat channel for testing and embedded web UIs.

    Messages are stored in an internal list and can be retrieved via
    :meth:`get_messages`.  No external dependencies are required.

    Parameters
    ----------
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "webchat"

    def __init__(
        self,
        *,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._messages: List[ChannelMessage] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Mark as connected (always succeeds for in-memory channel)."""
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
        """Append a message to the in-memory queue."""
        msg = ChannelMessage(
            channel=channel,
            sender="friday",
            content=content,
            conversation_id=conversation_id,
            metadata=metadata or {},
        )
        self._messages.append(msg)
        self._publish_sent(channel, content, conversation_id)
        return True

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["webchat"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    # -- webchat-specific helpers -----------------------------------------------

    def get_messages(self) -> List[ChannelMessage]:
        """Return all messages stored in the in-memory queue."""
        return self._messages

    def clear_messages(self) -> None:
        """Clear all messages from the in-memory queue."""
        self._messages.clear()

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


__all__ = ["WebChatChannel"]
