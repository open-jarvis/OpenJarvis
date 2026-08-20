"""LineChannel — LINE Messaging API adapter via line-bot-sdk."""

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


@ChannelRegistry.register("line")
class LineChannel(BaseChannel):
    """LINE messaging channel adapter.

    Uses the LINE Messaging API via ``line-bot-sdk``.

    Parameters
    ----------
    channel_access_token:
        LINE channel access token.  Falls back to ``LINE_CHANNEL_ACCESS_TOKEN``
        env var.
    channel_secret:
        LINE channel secret.  Falls back to ``LINE_CHANNEL_SECRET`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "line"

    def __init__(
        self,
        channel_access_token: str = "",
        *,
        channel_secret: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._channel_access_token = channel_access_token or os.environ.get(
            "LINE_CHANNEL_ACCESS_TOKEN", ""
        )
        self._channel_secret = channel_secret or os.environ.get(
            "LINE_CHANNEL_SECRET", ""
        )
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        if not self._channel_access_token or not self._channel_secret:
            logger.warning("No LINE channel_access_token or channel_secret configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import linebot  # noqa: F401
        except ImportError:
            raise ImportError(
                "line-bot-sdk not installed. Install with: uv sync --extra channel-line"
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
        """Send a push message to a LINE user or group.

        Parameters
        ----------
        channel:
            LINE user ID or group ID to send to.
        content:
            Text message content.
        """
        if not self._channel_access_token:
            logger.warning("Cannot send: no LINE credentials configured")
            return False

        try:
            from linebot.v3.messaging import (
                ApiClient,
                Configuration,
                MessagingApi,
                PushMessageRequest,
                TextMessage,
            )

            configuration = Configuration(
                access_token=self._channel_access_token,
            )
            with ApiClient(configuration) as api_client:
                api = MessagingApi(api_client)
                api.push_message(
                    PushMessageRequest(
                        to=channel,
                        messages=[TextMessage(text=content)],
                    )
                )

            self._publish_sent(channel, content, conversation_id)
            return True
        except ImportError:
            logger.debug("line-bot-sdk not installed")
            return False
        except Exception:
            logger.debug("LINE send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["line"]

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


__all__ = ["LineChannel"]
