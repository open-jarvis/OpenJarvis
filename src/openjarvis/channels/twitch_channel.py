"""TwitchChannel — Twitch chat adapter via twitchio."""

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


@ChannelRegistry.register("twitch")
class TwitchChannel(BaseChannel):
    """Twitch chat messaging channel adapter.

    Uses the Twitch IRC/EventSub API via ``twitchio``.

    Parameters
    ----------
    access_token:
        Twitch OAuth access token.  Falls back to ``TWITCH_ACCESS_TOKEN``
        env var.
    client_id:
        Twitch application client ID.  Falls back to ``TWITCH_CLIENT_ID``
        env var.
    nick:
        Bot nickname for IRC.  Falls back to ``TWITCH_NICK`` env var.
    initial_channels:
        Comma-separated list of channels to join.  Falls back to
        ``TWITCH_CHANNELS`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "twitch"

    def __init__(
        self,
        access_token: str = "",
        *,
        client_id: str = "",
        nick: str = "",
        initial_channels: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._access_token = access_token or os.environ.get("TWITCH_ACCESS_TOKEN", "")
        self._client_id = client_id or os.environ.get("TWITCH_CLIENT_ID", "")
        self._nick = nick or os.environ.get("TWITCH_NICK", "")
        self._initial_channels = initial_channels or os.environ.get(
            "TWITCH_CHANNELS", ""
        )
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        if not self._access_token:
            logger.warning("No Twitch access_token configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import twitchio  # noqa: F401
        except ImportError:
            raise ImportError(
                "twitchio not installed. Install with: uv sync --extra channel-twitch"
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
        """Send a chat message to a Twitch channel.

        Parameters
        ----------
        channel:
            Twitch channel name (without ``#`` prefix).
        content:
            Chat message content.

        Note
        ----
        For send-only usage this uses the Twitch Helix API to send a chat
        message.  A full interactive bot would use the twitchio event loop.
        """
        if not self._access_token:
            logger.warning("Cannot send: no Twitch credentials configured")
            return False

        try:
            import httpx

            url = "https://api.twitch.tv/helix/chat/messages"
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Client-Id": self._client_id,
                "Content-Type": "application/json",
            }
            payload: Dict[str, Any] = {
                "broadcaster_id": channel,
                "sender_id": self._nick,
                "message": content,
            }

            resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code < 300:
                self._publish_sent(channel, content, conversation_id)
                return True
            logger.warning("Twitch API returned status %d", resp.status_code)
            return False
        except Exception:
            logger.debug("Twitch send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["twitch"]

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


__all__ = ["TwitchChannel"]
