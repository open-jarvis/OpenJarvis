"""TeamsChannel — Microsoft Teams Bot Framework adapter."""

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


@ChannelRegistry.register("teams")
class TeamsChannel(BaseChannel):
    """Microsoft Teams channel adapter using the Bot Framework REST API.

    Parameters
    ----------
    app_id:
        Microsoft App ID.  Falls back to ``TEAMS_APP_ID`` env var.
    app_password:
        Microsoft App Password.  Falls back to ``TEAMS_APP_PASSWORD`` env var.
    service_url:
        Bot Framework service URL.  Falls back to ``TEAMS_SERVICE_URL`` env var
        (default ``https://smba.trafficmanager.net/teams``).
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "teams"

    def __init__(
        self,
        app_id: str = "",
        *,
        app_password: str = "",
        service_url: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._app_id = app_id or os.environ.get("TEAMS_APP_ID", "")
        self._app_password = app_password or os.environ.get("TEAMS_APP_PASSWORD", "")
        self._service_url = service_url or os.environ.get(
            "TEAMS_SERVICE_URL", "https://smba.trafficmanager.net/teams"
        )
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Mark as connected (send-only — no persistent connection)."""
        if not self._app_id or not self._app_password:
            logger.warning("No Teams app_id or app_password configured")
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
        """Send a message to a Teams conversation via the Bot Framework API."""
        if not self._app_id or not self._app_password:
            logger.warning("Cannot send: no Teams credentials configured")
            return False

        try:
            import httpx

            url = f"{self._service_url}/v3/conversations/{channel}/activities"
            headers = {
                "Authorization": f"Bearer {self._app_password}",
                "Content-Type": "application/json",
            }
            payload: Dict[str, Any] = {
                "type": "message",
                "text": content,
            }
            if conversation_id:
                payload["replyToId"] = conversation_id

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
                "Teams API returned status %d",
                resp.status_code,
            )
            return False
        except Exception:
            logger.debug("Teams send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["teams"]

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


__all__ = ["TeamsChannel"]
