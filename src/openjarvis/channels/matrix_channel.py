"""MatrixChannel — Matrix homeserver adapter."""

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


@ChannelRegistry.register("matrix")
class MatrixChannel(BaseChannel):
    """Matrix homeserver channel adapter.

    Parameters
    ----------
    homeserver:
        Matrix homeserver URL.  Falls back to ``MATRIX_HOMESERVER`` env var.
    access_token:
        Matrix access token.  Falls back to ``MATRIX_ACCESS_TOKEN`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "matrix"

    def __init__(
        self,
        homeserver: str = "",
        *,
        access_token: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._homeserver = homeserver or os.environ.get("MATRIX_HOMESERVER", "")
        self._access_token = access_token or os.environ.get("MATRIX_ACCESS_TOKEN", "")
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._txn_id = 0

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Mark as connected (send-only — no persistent connection)."""
        if not self._homeserver or not self._access_token:
            logger.warning("No Matrix homeserver or access_token configured")
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
        """Send a message to a Matrix room via the Client-Server API."""
        if not self._homeserver or not self._access_token:
            logger.warning("Cannot send: no Matrix credentials configured")
            return False

        try:
            import httpx

            self._txn_id += 1
            txn_id = self._txn_id
            url = (
                f"{self._homeserver}/_matrix/client/v3/rooms/"
                f"{channel}/send/m.room.message/{txn_id}"
            )
            headers = {
                "Authorization": f"Bearer {self._access_token}",
            }
            payload: Dict[str, Any] = {
                "msgtype": "m.text",
                "body": content,
            }

            resp = httpx.put(
                url,
                json=payload,
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code < 300:
                self._publish_sent(channel, content, conversation_id)
                return True
            logger.warning(
                "Matrix API returned status %d",
                resp.status_code,
            )
            return False
        except Exception:
            logger.debug("Matrix send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["matrix"]

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


__all__ = ["MatrixChannel"]
