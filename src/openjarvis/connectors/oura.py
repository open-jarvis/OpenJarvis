"""Oura Ring connector — sleep, readiness, and activity via REST API v2.

Uses a Personal Access Token (PAT) stored in the connector config dir.
All API calls are in module-level functions for easy mocking in tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_OURA_API_BASE = "https://api.ouraring.com/v2/usercollection"
_DEFAULT_TOKEN_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "oura.json")


def _oura_api_get(
    token: str, endpoint: str, params: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Call an Oura API v2 endpoint."""
    resp = httpx.get(
        f"{_OURA_API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("oura")
class OuraConnector(BaseConnector):
    """Sync sleep, readiness, and activity data from Oura Ring."""

    connector_id = "oura"
    display_name = "Oura Ring"
    auth_type = "token"

    def __init__(self, *, token_path: str = _DEFAULT_TOKEN_PATH) -> None:
        self._token_path = Path(token_path)
        self._status = SyncStatus()

    def _load_token(self) -> str:
        """Load the Oura PAT from disk."""
        data = json.loads(self._token_path.read_text(encoding="utf-8"))
        return data["token"]

    def set_token(self, token: str) -> None:
        """Validate and persist an Oura personal access token."""
        token = token.strip()
        if not token:
            raise ValueError("An Oura personal access token is required")
        _oura_api_get(token, "personal_info")
        from openjarvis.security.file_utils import secure_write_json

        secure_write_json(self._token_path, {"token": token})

    def is_connected(self) -> bool:
        try:
            return bool(self._load_token())
        except (OSError, KeyError, json.JSONDecodeError):
            return False

    def disconnect(self) -> None:
        if self._token_path.exists():
            self._token_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield Documents for sleep, readiness, and activity."""
        token = self._load_token()
        start = (since or datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")

        for data_type in ("sleep", "daily_readiness", "daily_activity"):
            data = _oura_api_get(
                token, data_type, params={"start_date": start, "end_date": end}
            )
            for item in data.get("data", []):
                day = item.get("day", start)
                yield Document(
                    doc_id=f"oura-{data_type}-{day}",
                    source="oura",
                    doc_type=data_type,
                    content=json.dumps(item),
                    title=f"Oura {data_type.replace('_', ' ').title()} — {day}",
                    timestamp=datetime.fromisoformat(day),
                    metadata={"data_type": data_type, "day": day},
                )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status
