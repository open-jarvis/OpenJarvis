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
        # can wake the async lifecycle owner (#784).
        self._client: Optional[Any] = None
        self._loop: Optional[Any] = None
        self._async_stop_event: Optional[asyncio.Event] = None
        self._runtime_lock = threading.Lock()

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

        The listener owns login, gateway connection, and client cleanup.
        ``disconnect`` publishes a durable stop request onto that loop; the
        listener races each async startup phase against it and performs the
        close itself. Status is only reported DISCONNECTED after the thread
        has actually terminated.
        """
        with self._lifecycle_lock:
            self._stop_event.set()

            with self._runtime_lock:
                loop = self._loop
                async_stop_event = self._async_stop_event
            if loop is not None and async_stop_event is not None:
                try:
                    loop.call_soon_threadsafe(async_stop_event.set)
                except RuntimeError:
                    logger.debug("Discord gateway event loop already closed")

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

    def _stop_requested(self, async_stop_event: asyncio.Event) -> bool:
        return self._stop_event.is_set() or async_stop_event.is_set()

    async def _run_stage_until_stopped(
        self,
        awaitable: Any,
        async_stop_event: asyncio.Event,
    ) -> bool:
        """Run one Discord startup stage, cancelling it when stop wins."""
        if self._stop_requested(async_stop_event):
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            return False

        stage_task = asyncio.create_task(awaitable)
        stop_task = asyncio.create_task(async_stop_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {stage_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done or self._stop_event.is_set():
                stage_task.cancel()
                await asyncio.gather(stage_task, return_exceptions=True)
                return False
            await stage_task
            return True
        finally:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)

    async def _run_gateway_lifecycle(
        self,
        client: Any,
        async_stop_event: asyncio.Event,
    ) -> None:
        """Own Discord login/connect/close with stop checks at each boundary."""
        try:
            if not await self._run_stage_until_stopped(
                client.login(self._token),
                async_stop_event,
            ):
                return
            if self._stop_requested(async_stop_event):
                return
            await self._run_stage_until_stopped(
                client.connect(reconnect=True),
                async_stop_event,
            )
        finally:
            await client.close()

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
            async_stop_event = asyncio.Event()
            with self._runtime_lock:
                self._client = client
                self._async_stop_event = async_stop_event
                self._loop = loop

            # A disconnect before these references were published remains in
            # the durable threading event. The owned lifecycle checks it before
            # login and races it against every asynchronous startup phase.
            loop.run_until_complete(
                self._run_gateway_lifecycle(client, async_stop_event)
            )
        except Exception:
            logger.debug("Discord gateway loop error", exc_info=True)
            if not self._stop_event.is_set():
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
            with self._runtime_lock:
                self._client = None
                self._async_stop_event = None
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
