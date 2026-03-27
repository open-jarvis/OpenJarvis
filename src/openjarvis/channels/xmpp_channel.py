"""XMPPChannel — XMPP/Jabber adapter via slixmpp."""

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


@ChannelRegistry.register("xmpp")
class XMPPChannel(BaseChannel):
    """XMPP (Jabber) messaging channel adapter.

    Uses the XMPP protocol via ``slixmpp``.

    Parameters
    ----------
    jid:
        XMPP JID (e.g. ``bot@example.com``).  Falls back to ``XMPP_JID``
        env var.
    password:
        XMPP account password.  Falls back to ``XMPP_PASSWORD`` env var.
    server:
        Optional XMPP server hostname override.  Falls back to
        ``XMPP_SERVER`` env var.
    port:
        XMPP server port (default 5222).  Falls back to ``XMPP_PORT`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "xmpp"

    def __init__(
        self,
        jid: str = "",
        *,
        password: str = "",
        server: str = "",
        port: int = 5222,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._jid = jid or os.environ.get("XMPP_JID", "")
        self._password = password or os.environ.get("XMPP_PASSWORD", "")
        self._server = server or os.environ.get("XMPP_SERVER", "")
        self._port = int(os.environ.get("XMPP_PORT", str(port)))
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        if not self._jid or not self._password:
            logger.warning("No XMPP jid or password configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import slixmpp  # noqa: F401
        except ImportError:
            raise ImportError(
                "slixmpp not installed. Install with: uv sync --extra channel-xmpp"
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
        """Send an XMPP message.

        Parameters
        ----------
        channel:
            Recipient JID (user or MUC room).
        content:
            Text message content.
        """
        if not self._jid or not self._password:
            logger.warning("Cannot send: no XMPP credentials configured")
            return False

        try:
            import slixmpp

            xmpp = slixmpp.ClientXMPP(self._jid, self._password)
            msg_type = (metadata or {}).get("type", "chat")

            msg = xmpp.make_message(
                mto=channel,
                mbody=content,
                mtype=msg_type,
            )
            msg.send()

            self._publish_sent(channel, content, conversation_id)
            return True
        except ImportError:
            logger.debug("slixmpp not installed")
            return False
        except Exception:
            logger.debug("XMPP send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["xmpp"]

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


__all__ = ["XMPPChannel"]
