"""Hacker News connector — top stories from the HN Firebase API.

No authentication required. All API calls are in module-level functions
for easy mocking in tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry

_HN_API_BASE = "https://hacker-news.firebaseio.com/v0"


def _hn_top_story_ids() -> List[int]:
    """Fetch the list of top story IDs."""
    resp = httpx.get(f"{_HN_API_BASE}/topstories.json", timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _hn_item(item_id: int) -> Dict[str, Any]:
    """Fetch a single HN item by ID."""
    resp = httpx.get(f"{_HN_API_BASE}/item/{item_id}.json", timeout=30.0)
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("hackernews")
class HackerNewsConnector(BaseConnector):
    """Fetch the current top stories from Hacker News."""

    connector_id = "hackernews"
    display_name = "Hacker News"
    auth_type = "local"

    def __init__(self) -> None:
        self._status = SyncStatus()

    def is_connected(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass  # No credentials to revoke

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield Documents for the top 5 Hacker News stories."""
        top_ids = _hn_top_story_ids()

        for story_id in top_ids[:5]:
            item = _hn_item(story_id)
            if item is None:
                continue

            title = item.get("title", "")
            score = item.get("score", 0)
            descendants = item.get("descendants", 0)
            url = item.get("url", "")
            by = item.get("by", "")
            ts = datetime.now()
            if item.get("time"):
                ts = datetime.fromtimestamp(item["time"])

            yield Document(
                doc_id=f"hn-{story_id}",
                source="hackernews",
                doc_type="story",
                content=f"Score: {score}, Comments: {descendants}",
                title=title,
                author=by,
                timestamp=ts,
                url=url or None,
                metadata={
                    "story_id": story_id,
                    "score": score,
                    "descendants": descendants,
                },
            )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status
