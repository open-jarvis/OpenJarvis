"""ZulipChannel — Zulip adapter via zulip Python bindings."""

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


@ChannelRegistry.register("zulip")
class ZulipChannel(BaseChannel):
    """Zulip messaging channel adapter.

    Uses the Zulip API via the official ``zulip`` Python package.

    Parameters
    ----------
    email:
        Zulip bot email address.  Falls back to ``ZULIP_EMAIL`` env var.
    api_key:
        Zulip bot API key.  Falls back to ``ZULIP_API_KEY`` env var.
    site:
        Zulip server URL (e.g. ``https://yourorg.zulipchat.com``).
        Falls back to ``ZULIP_SITE`` env var.
    zuliprc:
        Path to a ``~/.zuliprc`` config file.  Falls back to ``ZULIP_RC``
        env var.  If provided, ``email``/``api_key``/``site`` are ignored.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "zulip"

    def __init__(
        self,
        email: str = "",
        *,
        api_key: str = "",
        site: str = "",
        zuliprc: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._email = email or os.environ.get("ZULIP_EMAIL", "")
        self._api_key = api_key or os.environ.get("ZULIP_API_KEY", "")
        self._site = site or os.environ.get("ZULIP_SITE", "")
        self._zuliprc = zuliprc or os.environ.get("ZULIP_RC", "")
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        has_explicit_creds = self._email and self._api_key and self._site
        if not has_explicit_creds and not self._zuliprc:
            logger.warning("No Zulip credentials or zuliprc configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import zulip  # noqa: F401
        except ImportError:
            raise ImportError(
                "zulip not installed. Install with: uv sync --extra channel-zulip"
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
        """Send a message to a Zulip stream or user.

        Parameters
        ----------
        channel:
            Stream name for stream messages, or email address for direct
            messages.
        content:
            Message content (Markdown supported).
        """
        try:
            import zulip

            if self._zuliprc:
                client = zulip.Client(config_file=self._zuliprc)
            else:
                client = zulip.Client(
                    email=self._email,
                    api_key=self._api_key,
                    site=self._site,
                )

            meta = metadata or {}
            msg_type = meta.get("type", "stream")
            topic = meta.get("topic", "OpenJarvis")

            request: Dict[str, Any] = {
                "type": msg_type,
                "content": content,
            }
            if msg_type == "stream":
                request["to"] = channel
                request["topic"] = topic
            else:
                # Direct / private message
                request["to"] = [channel]

            result = client.send_message(request)
            if result.get("result") == "success":
                self._publish_sent(channel, content, conversation_id)
                return True
            logger.warning("Zulip API returned: %s", result.get("msg", ""))
            return False
        except ImportError:
            logger.debug("zulip not installed")
            return False
        except Exception:
            logger.debug("Zulip send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["zulip"]

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


__all__ = ["ZulipChannel"]
