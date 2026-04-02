"""Google Tasks connector — tasks due today, overdue, and recently completed.

Uses OAuth2 tokens via the shared Google OAuth helper module.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import load_tokens, resolve_google_credentials
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_TASKS_API_BASE = "https://tasks.googleapis.com/tasks/v1"
_DEFAULT_CREDENTIALS_PATH = str(
    DEFAULT_CONFIG_DIR / "connectors" / "google_tasks.json"
)


def _tasks_api_get(
    token: str, endpoint: str, params: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Call a Google Tasks API v1 endpoint."""
    resp = httpx.get(
        f"{_TASKS_API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("google_tasks")
class GoogleTasksConnector(BaseConnector):
    """Sync tasks from Google Tasks."""

    connector_id = "google_tasks"
    display_name = "Google Tasks"
    auth_type = "oauth"

    def __init__(self, *, credentials_path: str = "") -> None:
        self._credentials_path = Path(
            resolve_google_credentials(
                credentials_path or _DEFAULT_CREDENTIALS_PATH
            )
        )
        self._status = SyncStatus()

    def _get_access_token(self) -> str:
        tokens = load_tokens(str(self._credentials_path))
        return tokens.get("access_token") or tokens.get("token", "")

    def is_connected(self) -> bool:
        return self._credentials_path.exists()

    def disconnect(self) -> None:
        if self._credentials_path.exists():
            self._credentials_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        token = self._get_access_token()

        # List all task lists first
        task_lists = _tasks_api_get(token, "users/@me/lists")

        for tl in task_lists.get("items", []):
            tl_id = tl["id"]
            tl_title = tl.get("title", "My Tasks")

            # Get tasks from this list, updated since cutoff
            params: Dict[str, str] = {
                "showCompleted": "true",
                "showHidden": "false",
            }
            if since:
                params["updatedMin"] = since.isoformat() + "Z"

            tasks = _tasks_api_get(token, f"lists/{tl_id}/tasks", params=params)

            for task in tasks.get("items", []):
                due = task.get("due", "")
                status = task.get("status", "needsAction")

                ts = (
                    datetime.fromisoformat(
                        task.get("updated", "").replace("Z", "+00:00")
                    )
                    if task.get("updated")
                    else datetime.now()
                )

                yield Document(
                    doc_id=f"gtasks-{task['id']}",
                    source="google_tasks",
                    doc_type="task",
                    content=task.get("notes", ""),
                    title=task.get("title", "Untitled Task"),
                    timestamp=ts,
                    url=task.get("selfLink", ""),
                    metadata={
                        "task_list": tl_title,
                        "status": status,
                        "due": due,
                        "completed": task.get("completed", ""),
                    },
                )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status
