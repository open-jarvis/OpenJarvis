"""DiscordChannel — native Discord Bot API adapter."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)


@ChannelRegistry.register("discord")
class DiscordChannel(BaseChannel):
    """Native Discord channel adapter using the Discord REST API.

    Parameters
    ----------
    bot_token:
        Discord bot token.  Falls back to ``DISCORD_BOT_TOKEN`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "discord"

    def __init__(
        self,
        bot_token: str = "",
        *,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._token = bot_token or os.environ.get("DISCORD_BOT_TOKEN", "")
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Serialize listener registration and shutdown so a concurrent
        # connect() cannot clear a stop request after disconnect() returns.
        self._lifecycle_lock = threading.RLock()
        # Published by _gateway_loop while it's running so disconnect()
        # can actually interrupt client.start() (#784).
        self._client: Optional[Any] = None
        self._loop: Optional[Any] = None

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Start listening for incoming messages via discord.py gateway."""
        with self._lifecycle_lock:
            if self._listener_thread is not None and self._listener_thread.is_alive():
                # A gateway connection is already running; starting another
                # one duplicates message handling (#784).
                logger.warning(
                    "Discord channel already connected; ignoring duplicate connect()"
                )
                return

            if not self._token:
                logger.warning("No Discord bot token configured")
                self._status = ChannelStatus.ERROR
                return

            self._stop_event.clear()
            self._status = ChannelStatus.CONNECTING

            try:
                import discord  # noqa: F401

                listener = threading.Thread(
                    target=self._gateway_loop,
                    daemon=True,
                )
                self._listener_thread = listener
                self._status = ChannelStatus.CONNECTED
                listener.start()
                logger.info("Discord channel connected (gateway)")
            except ImportError:
                logger.info("discord.py not installed; send-only mode")
                self._status = ChannelStatus.CONNECTED
            except Exception:
                self._listener_thread = None
                self._status = ChannelStatus.ERROR
                logger.exception("Failed to start Discord listener")

    def disconnect(self) -> None:
        """Stop the listener thread.

        ``client.start()`` blocks the gateway thread inside its own event
        loop and never observed ``_stop_event`` (#784). Interrupt it by
        scheduling the coroutine ``client.close()`` onto that loop from
        here via ``asyncio.run_coroutine_threadsafe()`` and waiting for it
        to actually finish. Status is only ever reported as DISCONNECTED
        once the thread has actually terminated; otherwise a later
        ``connect()`` would spawn a duplicate gateway connection.
        """
        with self._lifecycle_lock:
            self._stop_event.set()

            client = self._client
            loop = self._loop
            if client is not None and loop is not None:
                try:
                    future = asyncio.run_coroutine_threadsafe(client.close(), loop)
                    future.result(timeout=5.0)
                except Exception:
                    logger.debug("Discord client.close() failed", exc_info=True)

            if self._listener_thread is not None:
                self._listener_thread.join(timeout=5.0)
                if self._listener_thread.is_alive():
                    logger.warning(
                        "Discord listener thread did not stop within timeout;"
                        " leaving status unchanged to avoid a duplicate"
                        " gateway connection"
                    )
                    return
                self._listener_thread = None

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
        """Send a message to a Discord channel via REST API."""
        if not self._token:
            logger.warning("Cannot send: no Discord bot token")
            return False
        # Defensive guard for #459 follow-up: an empty `channel` arg would
        # produce /channels//messages and silently 404. Better to fail
        # explicitly so the upstream bug (wrong field passed in) surfaces
        # in the warning log instead of silently blackholing the reply.
        if not channel:
            logger.warning(
                "Cannot send: no Discord channel destination "
                "(caller passed empty channel id)"
            )
            return False

        try:
            import httpx

            url = f"https://discord.com/api/v10/channels/{channel}/messages"
            headers = {
                "Authorization": f"Bot {self._token}",
                "Content-Type": "application/json",
            }
            payload: Dict[str, Any] = {"content": content}
            if conversation_id:
                payload["message_reference"] = {"message_id": conversation_id}

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
                "Discord API returned status %d: %s",
                resp.status_code,
                resp.text,
            )
            return False
        except Exception:
            logger.debug("Discord send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["discord"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

    def _gateway_loop(self) -> None:
        """Run the discord.py client in a background thread."""
        client: Any | None = None
        loop: asyncio.AbstractEventLoop | None = None
        try:
            import discord

            intents = discord.Intents.default()
            intents.message_content = True
            client = discord.Client(intents=intents)

            @client.event
            async def on_message(message):
                if message.author == client.user:
                    return
                cm = ChannelMessage(
                    channel="discord",
                    sender=str(message.author.id),
                    content=message.content,
                    message_id=str(message.id),
                    conversation_id=str(message.channel.id),
                )
                for handler in self._handlers:
                    try:
                        handler(cm)
                    except Exception:
                        logger.exception("Discord handler error")
                if self._bus is not None:
                    self._bus.publish(
                        EventType.CHANNEL_MESSAGE_RECEIVED,
                        {
                            "channel": cm.channel,
                            "sender": cm.sender,
                            "content": cm.content,
                            "message_id": cm.message_id,
                        },
                    )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._client = client
            self._loop = loop

            # disconnect() may run after the listener thread starts but before
            # these references are published. In that case it cannot schedule
            # client.close(), so honor the stop request before starting an
            # orphaned gateway connection.
            if self._stop_event.is_set():
                return

            loop.run_until_complete(client.start(self._token))
        except Exception:
            logger.debug("Discord gateway loop error", exc_info=True)
            self._status = ChannelStatus.ERROR
        finally:
            if loop is not None and not loop.is_closed():
                try:
                    if client is not None and not client.is_closed():
                        loop.run_until_complete(client.close())
                except Exception:
                    logger.debug("Discord client cleanup failed", exc_info=True)
                finally:
                    asyncio.set_event_loop(None)
                    loop.close()
            self._client = None
            self._loop = None

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


__all__ = ["DiscordChannel"]
