"""TelegramChannel — native Telegram Bot API adapter."""

from __future__ import annotations

import asyncio
import logging
import os
import textwrap
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


@ChannelRegistry.register("telegram")
class TelegramChannel(BaseChannel):
    """Native Telegram channel adapter using the Bot API.

    Parameters
    ----------
    bot_token:
        Telegram Bot API token.  Falls back to ``TELEGRAM_BOT_TOKEN`` env var.
    allowed_chat_ids:
        Comma-separated list of chat IDs allowed to interact.
    parse_mode:
        Message parse mode (``Markdown``, ``HTML``, etc.).
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "telegram"

    def __init__(
        self,
        bot_token: str = "",
        *,
        allowed_chat_ids: str = "",
        parse_mode: str = "Markdown",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._allowed_chat_ids = allowed_chat_ids
        self._parse_mode = parse_mode
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Serialize connect/disconnect all the way through listener
        # registration and shutdown.  Without this lock, disconnect() can
        # complete just before a concurrent connect() clears the shared stop
        # event, losing the stop request and leaving a fresh poller behind.
        self._lifecycle_lock = threading.RLock()
        # Published by _poll_loop while it's running so disconnect() can
        # wake the async lifecycle owner (#784).
        self._app: Optional[Any] = None
        self._loop: Optional[Any] = None
        self._async_stop_event: Optional[asyncio.Event] = None
        self._runtime_lock = threading.Lock()

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Start listening for incoming messages via long polling."""
        with self._lifecycle_lock:
            if self._listener_thread is not None and self._listener_thread.is_alive():
                # A poller is already running against this bot token; starting
                # another one causes Telegram's getUpdates API to return 409
                # Conflict for one or both pollers (#784).
                logger.warning(
                    "Telegram channel already connected; ignoring duplicate connect()"
                )
                return

            if not self._token:
                logger.warning("No Telegram bot token configured")
                self._status = ChannelStatus.ERROR
                return

            self._stop_event.clear()
            self._status = ChannelStatus.CONNECTING

            try:
                from telegram.ext import ApplicationBuilder  # noqa: F401

                listener = threading.Thread(
                    target=self._poll_loop,
                    daemon=True,
                )
                self._listener_thread = listener
                # Publish CONNECTED before starting.  A listener that fails
                # immediately can then reliably overwrite it with ERROR;
                # connect() must not race afterward and hide that failure.
                self._status = ChannelStatus.CONNECTED
                listener.start()
                logger.info("Telegram channel connected (long polling)")
            except ImportError:
                # python-telegram-bot not installed — send-only mode
                logger.info(
                    "python-telegram-bot not installed; send-only mode",
                )
                self._status = ChannelStatus.CONNECTED
            except Exception:
                self._listener_thread = None
                self._status = ChannelStatus.ERROR
                logger.exception("Failed to start Telegram listener")

    def disconnect(self) -> None:
        """Stop the listener thread.

        The listener owns every async startup/shutdown phase. ``disconnect``
        only publishes a stop request onto that owned loop, which is observed
        between initialize, polling startup, and application startup as well
        as during steady-state polling. Status is only reported DISCONNECTED
        once the thread has actually terminated.
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
                    logger.debug("Telegram poll loop's event loop already closed")

            if self._listener_thread is not None:
                self._listener_thread.join(timeout=5.0)
                if self._listener_thread.is_alive():
                    logger.warning(
                        "Telegram listener thread did not stop within timeout;"
                        " leaving status unchanged to avoid a duplicate poller"
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
        """Send a message to a Telegram chat via the Bot API."""
        if not self._token:
            logger.warning("Cannot send: no Telegram bot token")
            return False

        try:
            import httpx

            _TELEGRAM_MAX_LEN = 4096
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            # Canonical channel send contract (see BaseChannel.send): the first
            # positional ``channel`` arg is the DESTINATION (the Telegram chat
            # id).  ``conversation_id`` is the inbound message id used as a
            # reply/thread reference (``reply_to_message_id``).  We fall back to
            # ``conversation_id`` as the chat id only when ``channel`` is empty,
            # for backwards compatibility with legacy callers that passed the
            # chat id via ``conversation_id``.
            chat_id = channel or conversation_id
            reply_to = conversation_id if (channel and conversation_id) else ""
            chunks = textwrap.wrap(
                content,
                width=_TELEGRAM_MAX_LEN,
                break_long_words=True,
                replace_whitespace=False,
            )
            if not chunks:
                # Empty content wraps to an empty chunk list -- there is
                # nothing to send, so this must not fall through to the
                # success path below and report a message that was never
                # transmitted (#783).
                return False
            for chunk in chunks:
                payload: Dict[str, Any] = {
                    "chat_id": chat_id,
                    "text": chunk,
                }
                if self._parse_mode:
                    payload["parse_mode"] = self._parse_mode
                if reply_to:
                    payload["reply_to_message_id"] = reply_to

                resp = httpx.post(url, json=payload, timeout=10.0)
                if resp.status_code >= 300:
                    # Telegram rejects unparseable Markdown (lone asterisks,
                    # unclosed code fences, unescaped snake_case
                    # identifiers, etc.) with a 400 naming the cause in the
                    # response body. Retry once as plain text instead of
                    # dropping the message outright (#783).
                    if self._parse_mode and "can't parse entities" in resp.text.lower():
                        logger.warning(
                            "Telegram rejected Markdown formatting, "
                            "retrying as plain text: %s",
                            resp.text,
                        )
                        plain_payload = {
                            k: v for k, v in payload.items() if k != "parse_mode"
                        }
                        resp = httpx.post(url, json=plain_payload, timeout=10.0)
                    if resp.status_code >= 300:
                        logger.warning(
                            "Telegram API returned status %d: %s",
                            resp.status_code,
                            resp.text,
                        )
                        return False
            self._publish_sent(channel, content, conversation_id)
            return True
        except Exception:
            logger.debug("Telegram send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["telegram"]

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
        """Run one startup stage, cancelling it when disconnect wins the race."""
        if self._stop_requested(async_stop_event):
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            return False

        stage_task = asyncio.create_task(awaitable)
        stop_task = asyncio.create_task(async_stop_event.wait())
        try:
            done, _ = await asyncio.wait(
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

    async def _shutdown_partially_initialized_app(
        self,
        app: Any,
        updater: Any,
    ) -> None:
        """Release PTB resources even when ``Application.initialize`` was cut short.

        PTB intentionally makes ``Application.shutdown`` a no-op until its
        initialize method reaches the final bookkeeping assignment.  A stop can
        arrive after the bot's HTTP clients are initialized but before that
        assignment, so explicitly shut down the partially initialized
        components in that narrow state.
        """
        app_initialized = getattr(app, "_initialized", None)
        try:
            await app.shutdown()
        finally:
            if app_initialized is False:
                seen: set[int] = set()
                for component in (
                    updater,
                    getattr(app, "update_processor", None),
                    getattr(app, "bot", None),
                ):
                    if component is None or id(component) in seen:
                        continue
                    seen.add(id(component))
                    shutdown = getattr(component, "shutdown", None)
                    if not callable(shutdown):
                        continue
                    try:
                        await shutdown()
                    except Exception:
                        logger.debug(
                            "Failed to clean up partially initialized "
                            "Telegram component",
                            exc_info=True,
                        )

    async def _run_polling_lifecycle(
        self,
        app: Any,
        async_stop_event: asyncio.Event,
    ) -> None:
        """Own PTB's lifecycle so no stop can disappear inside run_polling.

        ``Application.run_polling`` checks its private stop marker before
        ``Updater.start_polling`` but not after it. A disconnect in that await
        therefore used to be lost and the subsequent ``run_forever`` stranded
        the thread. Explicit boundaries make the shared stop request durable.
        """
        updater = getattr(app, "updater", None)
        if updater is None:
            raise RuntimeError("Telegram application has no updater")

        try:
            if not await self._run_stage_until_stopped(
                app.initialize(), async_stop_event
            ):
                return
            if getattr(app, "post_init", None) is not None:
                if not await self._run_stage_until_stopped(
                    app.post_init(app), async_stop_event
                ):
                    return

            if not await self._run_stage_until_stopped(
                updater.start_polling(drop_pending_updates=True),
                async_stop_event,
            ):
                return

            if not await self._run_stage_until_stopped(app.start(), async_stop_event):
                return

            await async_stop_event.wait()
        finally:
            if getattr(updater, "running", False):
                await updater.stop()
            if getattr(app, "running", False):
                await app.stop()
                if getattr(app, "post_stop", None) is not None:
                    await app.post_stop(app)
            await self._shutdown_partially_initialized_app(app, updater)
            if getattr(app, "post_shutdown", None) is not None:
                await app.post_shutdown(app)

    def _poll_loop(self) -> None:
        """Long-poll for updates using python-telegram-bot."""
        loop: Any | None = None
        app: Any | None = None
        try:
            from telegram.ext import ApplicationBuilder, MessageHandler, filters

            # This thread owns the loop and every PTB startup/shutdown phase.
            # Publishing the stop event lets disconnect wake it safely from
            # another thread without asking PTB to stop a half-started app.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            async_stop_event = asyncio.Event()
            with self._runtime_lock:
                self._async_stop_event = async_stop_event
                self._loop = loop

            app = ApplicationBuilder().token(self._token).build()
            with self._runtime_lock:
                self._app = app

            def _handle_msg(update, context):
                msg = update.message
                if msg is None:
                    return
                cm = ChannelMessage(
                    channel="telegram",
                    sender=str(msg.from_user.id) if msg.from_user else "",
                    content=msg.text or "",
                    message_id=str(msg.message_id),
                    conversation_id=str(msg.chat.id),
                )
                # Enforce allow-list when configured
                if self._allowed_chat_ids:
                    _allowed = {
                        cid.strip()
                        for cid in self._allowed_chat_ids.split(",")
                        if cid.strip()
                    }
                    if cm.conversation_id not in _allowed:
                        logger.debug(
                            "Ignoring message from unlisted chat %s",
                            cm.conversation_id,
                        )
                        return
                for handler in self._handlers:
                    try:
                        handler(cm)
                    except Exception:
                        logger.exception("Telegram handler error")
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

            app.add_handler(MessageHandler(filters.TEXT, _handle_msg))
            loop.run_until_complete(self._run_polling_lifecycle(app, async_stop_event))
        except Exception:
            logger.debug("Telegram poll loop error", exc_info=True)
            if not self._stop_event.is_set():
                self._status = ChannelStatus.ERROR
        finally:
            with self._runtime_lock:
                self._app = None
                self._async_stop_event = None
                self._loop = None
            if loop is not None and not loop.is_closed():
                asyncio.set_event_loop(None)
                loop.close()
            if self._stop_event.is_set():
                self._status = ChannelStatus.DISCONNECTED

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


__all__ = ["TelegramChannel"]
