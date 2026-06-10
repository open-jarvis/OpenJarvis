"""ABC for channel implementations and shared types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class ChannelStatus(str, Enum):
    """Channel connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"


@dataclass(slots=True)
class ChannelMessage:
    """A message received from or sent to a channel."""

    channel: str
    sender: str
    content: str
    message_id: str = ""
    conversation_id: str = ""
    session_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# Type for message handler callbacks
ChannelHandler = Callable[[ChannelMessage], Optional[str]]


class BaseChannel(ABC):
    """Base class for all channel implementations.

    Subclasses must be registered via
    ``@ChannelRegistry.register("name")`` to become discoverable.
    """

    channel_id: str

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the channel gateway."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to the channel gateway."""

    @abstractmethod
    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        """Send a message to a specific channel. Returns True on success.

        Canonical send contract shared by **every** channel adapter:

        ``channel``
            The DESTINATION identifier — the per-adapter native id of the
            place the message goes (Discord/Slack channel id, Telegram chat
            id, email recipient address, ...).  This is *not* the channel
            TYPE label.  An incoming :class:`ChannelMessage` carries that
            destination in its ``conversation_id`` field (``channel`` there
            is only the type label such as ``"discord"``), so dispatch code
            replying to a message must pass ``cm.conversation_id`` here.
        ``conversation_id``
            An optional reply/thread reference — the native id of the
            message being replied to (Discord ``message_reference``, Slack
            ``thread_ts``, Telegram ``reply_to_message_id``, email
            ``In-Reply-To``, ...).  When replying to an inbound message this
            should be ``cm.message_id``, never the channel id.  Passing a
            channel id here yields broken references (e.g. Discord
            ``MESSAGE_REFERENCE_UNKNOWN_MESSAGE``).
        """

    @abstractmethod
    def status(self) -> ChannelStatus:
        """Return the current connection status."""

    @abstractmethod
    def list_channels(self) -> List[str]:
        """Return list of available channel names."""

    @abstractmethod
    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""


__all__ = ["BaseChannel", "ChannelHandler", "ChannelMessage", "ChannelStatus"]
