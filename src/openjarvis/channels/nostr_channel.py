"""NostrChannel — Nostr protocol adapter via pynostr."""

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


@ChannelRegistry.register("nostr")
class NostrChannel(BaseChannel):
    """Nostr decentralized messaging channel adapter.

    Uses the Nostr protocol via ``pynostr``.

    Parameters
    ----------
    private_key:
        Nostr private key (hex or nsec format).  Falls back to
        ``NOSTR_PRIVATE_KEY`` env var.
    relays:
        Comma-separated list of relay URLs.  Falls back to ``NOSTR_RELAYS``
        env var.  Default: ``wss://relay.damus.io``.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "nostr"

    def __init__(
        self,
        private_key: str = "",
        *,
        relays: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._private_key = private_key or os.environ.get("NOSTR_PRIVATE_KEY", "")
        relays_str = relays or os.environ.get("NOSTR_RELAYS", "wss://relay.damus.io")
        self._relays = [r.strip() for r in relays_str.split(",") if r.strip()]
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        if not self._private_key:
            logger.warning("No Nostr private_key configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import pynostr  # noqa: F401
        except ImportError:
            raise ImportError(
                "pynostr not installed. Install with: uv sync --extra channel-nostr"
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
        """Publish a Nostr event (kind 1 note or kind 4 DM).

        Parameters
        ----------
        channel:
            For public notes, this is ignored or used as a tag.  For
            encrypted DMs, this is the recipient public key (hex or npub).
        content:
            Note or message content.
        """
        if not self._private_key:
            logger.warning("Cannot send: no Nostr private_key configured")
            return False

        try:
            from pynostr.event import Event
            from pynostr.key import PrivateKey
            from pynostr.relay_manager import RelayManager

            if self._private_key.startswith("nsec"):
                pk = PrivateKey.from_nsec(self._private_key)
            else:
                pk = PrivateKey(bytes.fromhex(self._private_key))

            meta = metadata or {}
            kind = meta.get("kind", 1)

            event = Event(
                content=content,
                kind=kind,
                pub_key=pk.public_key.hex(),
            )
            if channel and kind == 4:
                # Encrypted DM tag
                event.add_tag("p", channel)
            pk.sign_event(event)

            relay_manager = RelayManager()
            for relay_url in self._relays:
                relay_manager.add_relay(relay_url)
            relay_manager.open_connections()
            relay_manager.publish_event(event)
            relay_manager.close_connections()

            self._publish_sent(channel, content, conversation_id)
            return True
        except ImportError:
            logger.debug("pynostr not installed")
            return False
        except Exception:
            logger.debug("Nostr send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["nostr"]

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


__all__ = ["NostrChannel"]
