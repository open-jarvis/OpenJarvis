"""TwitterChannel — native Twitter/X API adapter using tweepy."""

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


@ChannelRegistry.register("twitter")
class TwitterChannel(BaseChannel):
    """Native Twitter/X channel adapter using tweepy.

    Parameters
    ----------
    bearer_token:
        Twitter API v2 Bearer Token.  Falls back to ``TWITTER_BEARER_TOKEN``.
    api_key:
        Twitter API Key (consumer key).  Falls back to ``TWITTER_API_KEY``.
    api_secret:
        Twitter API Secret (consumer secret).  Falls back to ``TWITTER_API_SECRET``.
    access_token:
        Twitter Access Token.  Falls back to ``TWITTER_ACCESS_TOKEN``.
    access_secret:
        Twitter Access Token Secret.  Falls back to ``TWITTER_ACCESS_SECRET``.
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
        poll_interval: int = 60,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._bearer_token = bearer_token or os.environ.get(
            "TWITTER_BEARER_TOKEN",
            "",
        )
        self._api_key = api_key or os.environ.get("TWITTER_API_KEY", "")
        self._api_secret = api_secret or os.environ.get("TWITTER_API_SECRET", "")
        self._access_token = access_token or os.environ.get(
            "TWITTER_ACCESS_TOKEN",
            "",
        )
        self._access_secret = access_secret or os.environ.get(
            "TWITTER_ACCESS_SECRET",
            "",
        )
        self._poll_interval = poll_interval
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._client: Any = None
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Build a tweepy Client and optionally start polling for mentions."""
        if not self._bearer_token:
            logger.warning("No Twitter bearer token configured")
            self._status = ChannelStatus.ERROR
            return

        self._stop_event.clear()

        try:
            import tweepy  # noqa: F401

            self._client = tweepy.Client(
                bearer_token=self._bearer_token,
                consumer_key=self._api_key or None,
                consumer_secret=self._api_secret or None,
                access_token=self._access_token or None,
                access_token_secret=self._access_secret or None,
            )
            self._status = ChannelStatus.CONNECTED
            logger.info("Twitter channel connected")

            if self._access_token:
                self._poll_thread = threading.Thread(
                    target=self._poll_loop,
                    daemon=True,
                )
                self._poll_thread.start()
        except ImportError:
            logger.info("tweepy not installed; Twitter channel unavailable")
            self._status = ChannelStatus.ERROR
        except Exception:
            logger.debug("Twitter connect failed", exc_info=True)
            self._status = ChannelStatus.ERROR

    def disconnect(self) -> None:
        """Stop the polling thread and disconnect."""
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5.0)
            self._poll_thread = None
        self._client = None
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
        """Send a tweet or direct message.

        If *channel* is numeric, sends a DM via ``create_direct_message()``.
        Otherwise sends a tweet via ``create_tweet()``.  If *conversation_id*
        is provided, it is used as ``in_reply_to_tweet_id``.
        """
        if self._client is None:
            logger.warning("Cannot send: Twitter client not connected")
            return False

        try:
            if channel.isdigit():
                # Direct message to a user ID
                self._client.create_direct_message(
                    participant_id=int(channel),
                    text=content,
                )
            else:
                kwargs: Dict[str, Any] = {"text": content}
                if conversation_id:
                    kwargs["in_reply_to_tweet_id"] = int(conversation_id)
                self._client.create_tweet(**kwargs)

            self._publish_sent(channel, content, conversation_id)
            return True
        except Exception:
            logger.debug("Twitter send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["timeline", "dm"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

    def _poll_loop(self) -> None:
        """Poll for new mentions in a background thread."""
        since_id: Optional[str] = None

        while not self._stop_event.is_set():
            try:
                kwargs: Dict[str, Any] = {}
                if since_id:
                    kwargs["since_id"] = since_id

                me = self._client.get_me()
                if me and me.data:
                    user_id = me.data.id
                else:
                    self._stop_event.wait(self._poll_interval)
                    continue

                response = self._client.get_users_mentions(
                    id=user_id,
                    **kwargs,
                )

                if response and response.data:
                    for tweet in response.data:
                        since_id = str(tweet.id)
                        cm = ChannelMessage(
                            channel="twitter",
                            sender=str(getattr(tweet, "author_id", "")),
                            content=tweet.text,
                            message_id=str(tweet.id),
                            conversation_id=str(
                                getattr(tweet, "conversation_id", ""),
                            ),
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
            except Exception:
                logger.debug("Twitter poll error", exc_info=True)

            self._stop_event.wait(self._poll_interval)

    def _publish_sent(
        self,
        channel: str,
        content: str,
        conversation_id: str,
    ) -> None:
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
