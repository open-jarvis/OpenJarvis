"""RocketChatChannel — Rocket.Chat adapter via rocketchat_API."""

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


@ChannelRegistry.register("rocketchat")
class RocketChatChannel(BaseChannel):
    """Rocket.Chat messaging channel adapter.

    Uses the Rocket.Chat REST API via ``rocketchat_API``.

    Parameters
    ----------
    url:
        Rocket.Chat server URL.  Falls back to ``ROCKETCHAT_URL`` env var.
    user:
        Rocket.Chat username.  Falls back to ``ROCKETCHAT_USER`` env var.
    password:
        Rocket.Chat password.  Falls back to ``ROCKETCHAT_PASSWORD`` env var.
    auth_token:
        Rocket.Chat auth token (alternative to password).  Falls back to
        ``ROCKETCHAT_AUTH_TOKEN`` env var.
    user_id:
        Rocket.Chat user ID (used with auth_token).  Falls back to
        ``ROCKETCHAT_USER_ID`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "rocketchat"

    def __init__(
        self,
        url: str = "",
        *,
        user: str = "",
        password: str = "",
        auth_token: str = "",
        user_id: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._url = url or os.environ.get("ROCKETCHAT_URL", "")
        self._user = user or os.environ.get("ROCKETCHAT_USER", "")
        self._password = password or os.environ.get("ROCKETCHAT_PASSWORD", "")
        self._auth_token = auth_token or os.environ.get("ROCKETCHAT_AUTH_TOKEN", "")
        self._user_id = user_id or os.environ.get("ROCKETCHAT_USER_ID", "")
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        if not self._url:
            logger.warning("No Rocket.Chat URL configured")
            self._status = ChannelStatus.ERROR
            return
        has_password_auth = self._user and self._password
        has_token_auth = self._auth_token and self._user_id
        if not has_password_auth and not has_token_auth:
            logger.warning("No Rocket.Chat credentials configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import rocketchat_API  # noqa: F401
        except ImportError:
            raise ImportError(
                "rocketchat_API not installed. Install with: "
                "uv sync --extra channel-rocketchat"
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
        """Send a message to a Rocket.Chat channel or DM.

        Parameters
        ----------
        channel:
            Rocket.Chat channel name or room ID.
        content:
            Text message content.
        """
        if not self._url:
            logger.warning("Cannot send: no Rocket.Chat URL configured")
            return False

        try:
            from rocketchat_API import RocketChat

            if self._auth_token and self._user_id:
                rocket = RocketChat(
                    server_url=self._url,
                    auth_token=self._auth_token,
                    user_id=self._user_id,
                )
            else:
                rocket = RocketChat(
                    user=self._user,
                    password=self._password,
                    server_url=self._url,
                )

            rocket.chat_post_message(content, channel=channel)

            self._publish_sent(channel, content, conversation_id)
            return True
        except ImportError:
            logger.debug("rocketchat_API not installed")
            return False
        except Exception:
            logger.debug("Rocket.Chat send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["rocketchat"]

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


__all__ = ["RocketChatChannel"]
