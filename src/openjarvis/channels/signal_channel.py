"""SignalChannel — Signal adapter via signal-cli REST API."""

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


@ChannelRegistry.register("signal")
class SignalChannel(BaseChannel):
    """Signal channel adapter via signal-cli REST API (send-only).

    Parameters
    ----------
    api_url:
        Base URL of the signal-cli REST API.  Falls back to
        ``SIGNAL_API_URL`` env var.
    phone_number:
        Sender phone number registered with signal-cli.  Falls back to
        ``SIGNAL_PHONE_NUMBER`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "signal"

    def __init__(
        self,
        api_url: str = "",
        *,
        phone_number: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._api_url = api_url or os.environ.get("SIGNAL_API_URL", "")
        self._phone_number = phone_number or os.environ.get(
            "SIGNAL_PHONE_NUMBER",
            "",
        )
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Mark as connected (send-only — no persistent connection)."""
        if not self._api_url:
            logger.warning("No Signal API URL configured")
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
        """Send a message via the signal-cli REST API."""
        if not self._api_url:
            logger.warning("Cannot send: no Signal API URL configured")
            return False

        try:
            import httpx

            url = f"{self._api_url}/v2/send"
            payload: Dict[str, Any] = {
                "message": content,
                "number": self._phone_number,
                "recipients": [channel],
            }

            resp = httpx.post(url, json=payload, timeout=10.0)
            if resp.status_code < 300:
                self._publish_sent(channel, content, conversation_id)
                return True
            logger.warning(
                "Signal API returned status %d",
                resp.status_code,
            )
            return False
        except Exception:
            logger.debug("Signal send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["signal"]

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


__all__ = ["SignalChannel"]
