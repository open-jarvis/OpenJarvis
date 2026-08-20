"""SlackChannel — native Slack Web API adapter."""

from __future__ import annotations

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


@ChannelRegistry.register("slack")
class SlackChannel(BaseChannel):
    """Native Slack channel adapter using the Slack Web API.

    Parameters
    ----------
    bot_token:
        Slack Bot User OAuth Token.  Falls back to ``SLACK_BOT_TOKEN`` env var.
    app_token:
        Slack App-Level Token for Socket Mode.  Falls back to
        ``SLACK_APP_TOKEN`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "slack"

    def __init__(
        self,
        bot_token: str = "",
        *,
        app_token: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._token = bot_token or os.environ.get("SLACK_BOT_TOKEN", "")
        self._app_token = app_token or os.environ.get("SLACK_APP_TOKEN", "")
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Start listening for incoming messages via Slack Socket Mode."""
        if not self._token:
            logger.warning("No Slack bot token configured")
            self._status = ChannelStatus.ERROR
            return

        self._stop_event.clear()
        self._status = ChannelStatus.CONNECTING

        try:
            from slack_sdk.socket_mode import SocketModeClient  # noqa: F401

            if not self._app_token:
                logger.info("No app token for Socket Mode; send-only mode")
                self._status = ChannelStatus.CONNECTED
                return

            self._listener_thread = threading.Thread(
                target=self._socket_mode_loop,
                daemon=True,
            )
            self._listener_thread.start()
            self._status = ChannelStatus.CONNECTED
            logger.info("Slack channel connected (Socket Mode)")
        except ImportError:
            logger.info("slack-sdk not installed; send-only mode")
            self._status = ChannelStatus.CONNECTED

    def disconnect(self) -> None:
        """Stop the listener thread."""
        self._stop_event.set()
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=5.0)
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
        """Send a message to a Slack channel via the Web API."""
        if not self._token:
            logger.warning("Cannot send: no Slack bot token")
            return False

        try:
            import httpx

            url = "https://slack.com/api/chat.postMessage"
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            }
            payload: Dict[str, Any] = {
                "channel": channel,
                "text": content,
            }
            if conversation_id:
                payload["thread_ts"] = conversation_id

            resp = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code < 300:
                data = resp.json()
                if data.get("ok"):
                    self._publish_sent(channel, content, conversation_id)
                    return True
                logger.warning("Slack API error: %s", data.get("error"))
                return False
            logger.warning(
                "Slack API returned status %d",
                resp.status_code,
            )
            return False
        except Exception:
            logger.debug("Slack send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["slack"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

    def _socket_mode_loop(self) -> None:
        """Run Slack Socket Mode client in a background thread."""
        try:
            from slack_sdk.socket_mode import SocketModeClient
            from slack_sdk.socket_mode.request import SocketModeRequest
            from slack_sdk.socket_mode.response import SocketModeResponse
            from slack_sdk.web import WebClient

            client = SocketModeClient(
                app_token=self._app_token,
                web_client=WebClient(token=self._token),
            )

            def _handle_event(client_obj, req: SocketModeRequest):
                if req.type == "events_api":
                    event = req.payload.get("event", {})
                    if event.get("type") == "message" and "subtype" not in event:
                        cm = ChannelMessage(
                            channel="slack",
                            sender=event.get("user", ""),
                            content=event.get("text", ""),
                            message_id=event.get("ts", ""),
                            conversation_id=event.get("channel", ""),
                        )
                        for handler in self._handlers:
                            try:
                                handler(cm)
                            except Exception:
                                logger.exception("Slack handler error")
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
                    client_obj.send_socket_mode_response(
                        SocketModeResponse(envelope_id=req.envelope_id),
                    )

            client.socket_mode_request_listeners.append(_handle_event)
            client.connect()

            while not self._stop_event.is_set():
                self._stop_event.wait(1.0)

            client.disconnect()
        except Exception:
            logger.debug("Slack Socket Mode loop error", exc_info=True)
            self._status = ChannelStatus.ERROR

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


__all__ = ["SlackChannel"]
