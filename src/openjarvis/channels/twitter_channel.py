"""TwitterChannel — Twitter/X API v2 adapter using OAuth 1.0a."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import threading
import time
import urllib.parse
import uuid
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

_API_BASE = "https://api.twitter.com/2"


# ---------------------------------------------------------------------------
# OAuth 1.0a signing (stdlib only — no authlib dependency)
# ---------------------------------------------------------------------------


class _OAuth1Auth:
    """Minimal OAuth 1.0a request signer for httpx.

    Implements HMAC-SHA1 signature as required by the Twitter v2 API for
    user-context endpoints (posting tweets).
    """

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_secret: str,
    ) -> None:
        self._consumer_key = consumer_key
        self._consumer_secret = consumer_secret
        self._access_token = access_token
        self._access_secret = access_secret

    def __call__(self, request):  # noqa: ANN001
        """Sign *request* in-place and return it (httpx auth protocol)."""
        oauth_params = {
            "oauth_consumer_key": self._consumer_key,
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self._access_token,
            "oauth_version": "1.0",
        }

        # Build signature base string
        method = request.method.upper()
        base_url = str(request.url).split("?")[0]

        # Merge query params + oauth params for signing
        all_params: dict[str, str] = dict(oauth_params)
        for key, value in request.url.params.items():
            all_params[key] = value

        param_str = "&".join(
            f"{_pct(k)}={_pct(v)}"
            for k, v in sorted(all_params.items())
        )
        base_string = f"{method}&{_pct(base_url)}&{_pct(param_str)}"

        signing_key = f"{_pct(self._consumer_secret)}&{_pct(self._access_secret)}"
        signature = base64.b64encode(
            hmac.new(
                signing_key.encode(), base_string.encode(), hashlib.sha1,
            ).digest(),
        ).decode()

        oauth_params["oauth_signature"] = signature

        auth_header = "OAuth " + ", ".join(
            f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth_params.items())
        )
        request.headers["Authorization"] = auth_header
        return request


def _pct(value: str) -> str:
    """Percent-encode per RFC 5849."""
    return urllib.parse.quote(str(value), safe="")


# ---------------------------------------------------------------------------
# Channel implementation
# ---------------------------------------------------------------------------


@ChannelRegistry.register("twitter")
class TwitterChannel(BaseChannel):
    """Native Twitter/X channel adapter using the v2 API.

    Parameters
    ----------
    bearer_token:
        Bearer token for read endpoints.  Falls back to
        ``TWITTER_BEARER_TOKEN`` env var.
    api_key / api_secret:
        OAuth 1.0a consumer credentials.  Fall back to
        ``TWITTER_API_KEY`` / ``TWITTER_API_SECRET``.
    access_token / access_secret:
        OAuth 1.0a user credentials.  Fall back to
        ``TWITTER_ACCESS_TOKEN`` / ``TWITTER_ACCESS_SECRET``.
    bot_user_id:
        Numeric Twitter user ID for the bot account.  Falls back to
        ``TWITTER_BOT_USER_ID``.
    poll_interval:
        Seconds between mention polls (default 60).
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "twitter"

    def __init__(
        self,
        bearer_token: str = "",
        *,
        api_key: str = "",
        api_secret: str = "",
        access_token: str = "",
        access_secret: str = "",
        bot_user_id: str = "",
        poll_interval: int = 60,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._bearer = bearer_token or os.environ.get("TWITTER_BEARER_TOKEN", "")
        self._api_key = api_key or os.environ.get("TWITTER_API_KEY", "")
        self._api_secret = api_secret or os.environ.get("TWITTER_API_SECRET", "")
        self._access_token = access_token or os.environ.get("TWITTER_ACCESS_TOKEN", "")
        self._access_secret = access_secret or os.environ.get(
            "TWITTER_ACCESS_SECRET", "",
        )
        self._bot_user_id = bot_user_id or os.environ.get("TWITTER_BOT_USER_ID", "")
        self._poll_interval = poll_interval
        self._bus = bus

        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._since_id: Optional[str] = None

    # -- OAuth helper -------------------------------------------------------

    def _oauth(self) -> _OAuth1Auth:
        return _OAuth1Auth(
            self._api_key, self._api_secret,
            self._access_token, self._access_secret,
        )

    # -- connection lifecycle -----------------------------------------------

    def connect(self) -> None:
        """Validate credentials and start mention polling."""
        if not self._bearer:
            logger.warning("No Twitter bearer token configured")
            self._status = ChannelStatus.ERROR
            return

        self._stop_event.clear()
        self._status = ChannelStatus.CONNECTING

        self._listener_thread = threading.Thread(
            target=self._poll_mentions, daemon=True,
        )
        self._listener_thread.start()
        self._status = ChannelStatus.CONNECTED
        logger.info("Twitter channel connected (polling mentions)")

    def disconnect(self) -> None:
        """Stop the polling thread."""
        self._stop_event.set()
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=5.0)
            self._listener_thread = None
        self._status = ChannelStatus.DISCONNECTED

    # -- send / receive -----------------------------------------------------

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        """Post a tweet, optionally as a reply.

        *channel* is ignored (tweets go to the bot's timeline).
        *conversation_id* is used as ``reply.in_reply_to_tweet_id`` when set.
        Content is truncated to 280 characters.
        """
        if not self._api_key:
            logger.warning("Cannot send: no Twitter OAuth credentials")
            return False

        text = content[:280]

        try:
            import httpx

            payload: Dict[str, Any] = {"text": text}
            if conversation_id:
                payload["reply"] = {"in_reply_to_tweet_id": conversation_id}

            resp = httpx.post(
                f"{_API_BASE}/tweets",
                json=payload,
                auth=self._oauth(),
                timeout=10.0,
            )
            if resp.status_code < 300:
                self._publish_sent(channel, text, conversation_id)
                return True
            logger.warning(
                "Twitter API returned status %d: %s",
                resp.status_code,
                resp.text,
            )
            return False
        except Exception:
            logger.debug("Twitter send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["twitter"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming mentions."""
        self._handlers.append(handler)

    # -- internal helpers ---------------------------------------------------

    def _poll_mentions(self) -> None:
        """Poll ``GET /2/users/{id}/mentions`` on a fixed interval."""
        try:
            import httpx
        except ImportError:
            logger.debug("httpx not available for Twitter polling")
            self._status = ChannelStatus.ERROR
            return

        headers = {"Authorization": f"Bearer {self._bearer}"}
        url = f"{_API_BASE}/users/{self._bot_user_id}/mentions"

        while not self._stop_event.is_set():
            try:
                params: Dict[str, str] = {
                    "tweet.fields": "author_id,conversation_id,created_at",
                }
                if self._since_id:
                    params["since_id"] = self._since_id

                resp = httpx.get(
                    url, headers=headers, params=params, timeout=10.0,
                )
                if resp.status_code < 300:
                    data = resp.json()
                    tweets = data.get("data", [])
                    for tweet in tweets:
                        tweet_id = tweet["id"]
                        cm = ChannelMessage(
                            channel="twitter",
                            sender=tweet.get("author_id", ""),
                            content=tweet.get("text", ""),
                            message_id=tweet_id,
                            conversation_id=tweet.get("conversation_id", ""),
                        )
                        for handler in self._handlers:
                            try:
                                handler(cm)
                            except Exception:
                                logger.exception("Twitter handler error")
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
                        # Track highest ID to avoid reprocessing
                        if self._since_id is None or tweet_id > self._since_id:
                            self._since_id = tweet_id
                else:
                    logger.warning(
                        "Twitter mentions API returned %d: %s",
                        resp.status_code,
                        resp.text,
                    )
            except Exception:
                logger.debug("Twitter poll error", exc_info=True)

            self._stop_event.wait(self._poll_interval)

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


__all__ = ["TwitterChannel"]
