"""MastodonChannel — Mastodon adapter via Mastodon.py."""

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


@ChannelRegistry.register("mastodon")
class MastodonChannel(BaseChannel):
    """Mastodon messaging channel adapter.

    Uses the Mastodon API via ``Mastodon.py``.

    Parameters
    ----------
    api_base_url:
        Mastodon instance URL (e.g. ``https://mastodon.social``).  Falls back
        to ``MASTODON_API_BASE_URL`` env var.
    access_token:
        Mastodon access token.  Falls back to ``MASTODON_ACCESS_TOKEN`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "mastodon"

    def __init__(
        self,
        api_base_url: str = "",
        *,
        access_token: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._api_base_url = api_base_url or os.environ.get("MASTODON_API_BASE_URL", "")
        self._access_token = access_token or os.environ.get("MASTODON_ACCESS_TOKEN", "")
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        if not self._api_base_url or not self._access_token:
            logger.warning("No Mastodon api_base_url or access_token configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import mastodon  # noqa: F401
        except ImportError:
            raise ImportError(
                "Mastodon.py not installed. Install with: "
                "uv sync --extra channel-mastodon"
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
        """Post a status or send a direct message on Mastodon.

        Parameters
        ----------
        channel:
            Visibility level (``public``, ``unlisted``, ``private``,
            ``direct``) or a username to DM (prefix with ``@``).
        content:
            Toot / message content.
        """
        if not self._api_base_url or not self._access_token:
            logger.warning("Cannot send: no Mastodon credentials configured")
            return False

        try:
            from mastodon import Mastodon

            client = Mastodon(
                access_token=self._access_token,
                api_base_url=self._api_base_url,
            )

            visibility = "public"
            if channel in ("public", "unlisted", "private", "direct"):
                visibility = channel
            elif channel.startswith("@"):
                # Direct message — prepend mention
                visibility = "direct"
                if not content.startswith(channel):
                    content = f"{channel} {content}"

            in_reply_to_id = conversation_id or None
            client.status_post(
                content,
                visibility=visibility,
                in_reply_to_id=in_reply_to_id,
            )

            self._publish_sent(channel, content, conversation_id)
            return True
        except ImportError:
            logger.debug("Mastodon.py not installed")
            return False
        except Exception:
            logger.debug("Mastodon send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["mastodon"]

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


__all__ = ["MastodonChannel"]
