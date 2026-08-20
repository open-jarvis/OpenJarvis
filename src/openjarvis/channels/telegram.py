"""TelegramChannel — native Telegram Bot API adapter."""

from __future__ import annotations

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
        # actually interrupt Application.run_polling() (#784).
        self._app: Optional[Any] = None
        self._loop: Optional[Any] = None

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

        ``app.run_polling()`` blocks the listener thread inside its own
        event loop and never observed ``_stop_event`` (#784). Interrupt it
        via ``Application.stop_running()`` -- which internally calls
        ``asyncio.get_running_loop().stop()`` and so is only safe to call
        from *within* that loop's own thread -- scheduled here with
        ``loop.call_soon_threadsafe()``. Status is only ever reported as
        DISCONNECTED once the thread has actually terminated; otherwise a
        later ``connect()`` would spawn a duplicate poller.
        """
        with self._lifecycle_lock:
            self._stop_event.set()

            app = self._app
            loop = self._loop
            if app is not None and loop is not None:
                try:
                    loop.call_soon_threadsafe(app.stop_running)
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

    def _poll_loop(self) -> None:
        """Long-poll for updates using python-telegram-bot."""
        loop: Any | None = None
        try:
            import asyncio

            from telegram.ext import ApplicationBuilder, MessageHandler, filters

            # Create and set this thread's event loop ourselves so it's
            # available before app.run_polling() starts (it picks up the
            # already-set loop via asyncio.get_event_loop() rather than
            # creating its own) -- disconnect() needs a reference to
            # schedule Application.stop_running() onto it (#784).
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop

            app = ApplicationBuilder().token(self._token).build()
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
            # disconnect() can win the race before _app is published. It
            # cannot call stop_running() in that window, so do not enter the
            # blocking poller after a stop has already been requested.
            if self._stop_event.is_set():
                return
            app.run_polling(stop_signals=None, drop_pending_updates=True)
        except Exception:
            logger.debug("Telegram poll loop error", exc_info=True)
            self._status = ChannelStatus.ERROR
        finally:
            self._app = None
            self._loop = None
            if loop is not None and not loop.is_closed():
                asyncio.set_event_loop(None)
                loop.close()

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
