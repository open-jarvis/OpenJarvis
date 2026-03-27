"""RedditChannel — Reddit adapter via praw."""

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


@ChannelRegistry.register("reddit")
class RedditChannel(BaseChannel):
    """Reddit messaging channel adapter.

    Uses the Reddit API via ``praw`` (Python Reddit API Wrapper).

    Parameters
    ----------
    client_id:
        Reddit app client ID.  Falls back to ``REDDIT_CLIENT_ID`` env var.
    client_secret:
        Reddit app client secret.  Falls back to ``REDDIT_CLIENT_SECRET`` env var.
    username:
        Reddit username.  Falls back to ``REDDIT_USERNAME`` env var.
    password:
        Reddit password.  Falls back to ``REDDIT_PASSWORD`` env var.
    user_agent:
        User-agent string for API requests.  Falls back to
        ``REDDIT_USER_AGENT`` env var.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "reddit"

    def __init__(
        self,
        client_id: str = "",
        *,
        client_secret: str = "",
        username: str = "",
        password: str = "",
        user_agent: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._client_id = client_id or os.environ.get("REDDIT_CLIENT_ID", "")
        self._client_secret = client_secret or os.environ.get(
            "REDDIT_CLIENT_SECRET", ""
        )
        self._username = username or os.environ.get("REDDIT_USERNAME", "")
        self._password = password or os.environ.get("REDDIT_PASSWORD", "")
        self._user_agent = user_agent or os.environ.get(
            "REDDIT_USER_AGENT", "openjarvis:v1.0"
        )
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._reddit: Any = None

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Validate credentials and mark as connected."""
        if not self._client_id or not self._client_secret:
            logger.warning("No Reddit client_id or client_secret configured")
            self._status = ChannelStatus.ERROR
            return
        try:
            import praw  # noqa: F401
        except ImportError:
            raise ImportError(
                "praw not installed. Install with: uv sync --extra channel-reddit"
            )
        self._status = ChannelStatus.CONNECTED

    def disconnect(self) -> None:
        """Mark as disconnected."""
        self._reddit = None
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
        """Send a message or comment on Reddit.

        Parameters
        ----------
        channel:
            Subreddit name (without ``r/`` prefix) or a Reddit thing ID to
            reply to.
        content:
            Text content for the submission or comment.
        """
        if not self._client_id or not self._client_secret:
            logger.warning("Cannot send: no Reddit credentials configured")
            return False

        try:
            import praw

            reddit = praw.Reddit(
                client_id=self._client_id,
                client_secret=self._client_secret,
                username=self._username,
                password=self._password,
                user_agent=self._user_agent,
            )

            if conversation_id:
                # Reply to an existing comment/submission
                comment = reddit.comment(conversation_id)
                comment.reply(content)
            else:
                # Submit as a new text post to the subreddit
                subreddit = reddit.subreddit(channel)
                title = (metadata or {}).get("title", "OpenJarvis Message")
                subreddit.submit(title=title, selftext=content)

            self._publish_sent(channel, content, conversation_id)
            return True
        except ImportError:
            logger.debug("praw not installed")
            return False
        except Exception:
            logger.debug("Reddit send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["reddit"]

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


__all__ = ["RedditChannel"]
