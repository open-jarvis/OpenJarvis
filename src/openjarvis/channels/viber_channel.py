"""ViberChannel — Viber adapter via viberbot."""

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


@ChannelRegistry.register("viber")
class ViberChannel(BaseChannel):
    """Viber messaging channel adapter.

    Uses the Viber Bot API via ``viberbot``.

    Parameters
    ----------
    auth_token:
        Viber bot auth token.  Falls back to ``VIBER_AUTH_TOKEN`` env var.
    name:
        Bot display name.  Falls back to ``VIBER_BOT_NAME`` env var.
    avatar:
        Bot avatar URL.  Falls back to ``VIBER_BOT_AVATAR`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "viber"

    def __init__(
        self,
        auth_token: str = "",
        *,
        name: str = "",
        avatar: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._auth_token = auth_token or os.environ.get("VIBER_AUTH_TOKEN", "")
        self._name = name or os.environ.get("VIBER_BOT_NAME", "OpenJarvis")
        self._avatar = avatar or os.environ.get("VIBER_BOT_AVATAR", "")
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        if not self._auth_token:
            logger.warning("No Viber auth_token configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import viberbot  # noqa: F401
        except ImportError:
            raise ImportError(
                "viberbot not installed. Install with: uv sync --extra channel-viber"
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
        """Send a message to a Viber user.

        Parameters
        ----------
        channel:
            Viber user ID to send to.
        content:
            Text message content.
        """
        if not self._auth_token:
            logger.warning("Cannot send: no Viber credentials configured")
            return False

        try:
            from viberbot import Api, BotConfiguration
            from viberbot.api.messages.text_message import TextMessage

            config = BotConfiguration(
                name=self._name,
                avatar=self._avatar,
                auth_token=self._auth_token,
            )
            api = Api(config)
            api.send_messages(channel, [TextMessage(text=content)])

            self._publish_sent(channel, content, conversation_id)
            return True
        except ImportError:
            logger.debug("viberbot not installed")
            return False
        except Exception:
            logger.debug("Viber send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["viber"]

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


__all__ = ["ViberChannel"]
