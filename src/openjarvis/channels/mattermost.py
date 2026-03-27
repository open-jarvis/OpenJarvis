"""MattermostChannel — Mattermost REST API adapter."""

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


@ChannelRegistry.register("mattermost")
class MattermostChannel(BaseChannel):
    """Mattermost channel adapter using the REST API.

    Parameters
    ----------
    url:
        Mattermost server URL.  Falls back to ``MATTERMOST_URL`` env var.
    token:
        Mattermost personal access token or bot token.  Falls back to
        ``MATTERMOST_TOKEN`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "mattermost"

    def __init__(
        self,
        url: str = "",
        *,
        token: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._url = url or os.environ.get("MATTERMOST_URL", "")
        self._token = token or os.environ.get("MATTERMOST_TOKEN", "")
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Mark as connected (send-only — no persistent connection)."""
        if not self._url or not self._token:
            logger.warning("No Mattermost URL or token configured")
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
        """Send a message to a Mattermost channel via the REST API."""
        if not self._url or not self._token:
            logger.warning("Cannot send: no Mattermost credentials configured")
            return False

        try:
            import httpx

            url = f"{self._url}/api/v4/posts"
            headers = {
                "Authorization": f"Bearer {self._token}",
            }
            payload: Dict[str, Any] = {
                "channel_id": channel,
                "message": content,
            }
            if conversation_id:
                payload["root_id"] = conversation_id

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
                "Mattermost API returned status %d",
                resp.status_code,
            )
            return False
        except Exception:
            logger.debug("Mattermost send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["mattermost"]

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


__all__ = ["MattermostChannel"]
