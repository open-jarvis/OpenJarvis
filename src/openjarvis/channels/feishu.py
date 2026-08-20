"""FeishuChannel — Feishu (Lark) adapter."""

from __future__ import annotations

import json
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


@ChannelRegistry.register("feishu")
class FeishuChannel(BaseChannel):
    """Feishu (Lark) channel adapter.

    Parameters
    ----------
    app_id:
        Feishu App ID.  Falls back to ``FEISHU_APP_ID`` env var.
    app_secret:
        Feishu App Secret.  Falls back to ``FEISHU_APP_SECRET`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "feishu"

    def __init__(
        self,
        app_id: str = "",
        *,
        app_secret: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._app_id = app_id or os.environ.get("FEISHU_APP_ID", "")
        self._app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET", "")
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Mark as connected (send-only — no persistent connection)."""
        if not self._app_id or not self._app_secret:
            logger.warning("No Feishu app_id or app_secret configured")
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
        """Send a message to a Feishu chat via the Open API."""
        if not self._app_id or not self._app_secret:
            logger.warning("Cannot send: no Feishu credentials configured")
            return False

        try:
            import httpx

            # Obtain tenant_access_token
            token_url = (
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            )
            token_resp = httpx.post(
                token_url,
                json={
                    "app_id": self._app_id,
                    "app_secret": self._app_secret,
                },
                timeout=10.0,
            )
            if token_resp.status_code >= 300:
                logger.warning(
                    "Feishu token request returned status %d",
                    token_resp.status_code,
                )
                return False
            tenant_token = token_resp.json().get("tenant_access_token", "")
            if not tenant_token:
                logger.warning("Feishu token response missing tenant_access_token")
                return False

            # Send message
            msg_url = (
                "https://open.feishu.cn/open-apis/im/v1/messages"
                "?receive_id_type=chat_id"
            )
            headers = {
                "Authorization": f"Bearer {tenant_token}",
                "Content-Type": "application/json",
            }
            payload: Dict[str, Any] = {
                "receive_id": channel,
                "msg_type": "text",
                "content": json.dumps({"text": content}),
            }

            resp = httpx.post(
                msg_url,
                json=payload,
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code < 300:
                self._publish_sent(channel, content, conversation_id)
                return True
            logger.warning(
                "Feishu API returned status %d",
                resp.status_code,
            )
            return False
        except Exception:
            logger.debug("Feishu send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["feishu"]

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


__all__ = ["FeishuChannel"]
