"""GitHub Notifications connector — unread notifications via GitHub REST API.

Uses a Personal Access Token stored in the connector config dir.
All API calls are in module-level functions for easy mocking in tests.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_DEFAULT_TOKEN_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "github.json")


def _github_api_get(
    token: str, params: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """Fetch notifications from the GitHub API."""
    resp = httpx.get(
        "https://api.github.com/notifications",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("github_notifications")
class GitHubNotificationsConnector(BaseConnector):
    """Sync unread notifications from GitHub."""

    connector_id = "github_notifications"
    display_name = "GitHub Notifications"
    auth_type = "token"

    def __init__(self, *, token_path: str = _DEFAULT_TOKEN_PATH) -> None:
        self._token_path = Path(token_path)
        self._status = SyncStatus()

    def _load_token(self) -> str:
        """Load the GitHub PAT from disk."""
        data = json.loads(self._token_path.read_text(encoding="utf-8"))
        return data["token"]

    def is_connected(self) -> bool:
        return self._token_path.exists()

    def disconnect(self) -> None:
        if self._token_path.exists():
            self._token_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield Documents for each GitHub notification."""
        token = self._load_token()
        params: Dict[str, str] = {}
        if since is not None:
            params["since"] = f"{since.isoformat()}Z"

        notifications = _github_api_get(token, params=params)

        for notif in notifications:
            subject = notif.get("subject", {})
            repo = notif.get("repository", {}).get("full_name", "")
            reason = notif.get("reason", "")
            notif_type = subject.get("type", "")
            title = subject.get("title", "")
            notif_id = notif.get("id", "")
            updated_at = notif.get("updated_at", "")

            content = f"Reason: {reason}, Repository: {repo}"
            ts = datetime.now()
            if updated_at:
                try:
                    ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                except ValueError:
                    pass

            yield Document(
                doc_id=f"github-notification-{notif_id}",
                source="github_notifications",
                doc_type="notification",
                content=content,
                title=title,
                timestamp=ts,
                url=subject.get("url"),
                metadata={
                    "reason": reason,
                    "repo": repo,
                    "type": notif_type,
                },
            )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status
