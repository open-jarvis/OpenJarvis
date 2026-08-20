"""Spotify connector — recently played tracks via Spotify Web API.

Uses OAuth2 tokens stored locally. Requires user-read-recently-played scope.
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

_SPOTIFY_API_BASE = "https://api.spotify.com/v1"
_SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
_DEFAULT_TOKEN_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "spotify.json")


def _spotify_api_get(
    token: str, endpoint: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Call a Spotify Web API endpoint."""
    resp = httpx.get(
        f"{_SPOTIFY_API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("spotify")
class SpotifyConnector(BaseConnector):
    """Sync recently played tracks from Spotify."""

    connector_id = "spotify"
    display_name = "Spotify"
    auth_type = "oauth"

    def __init__(self, *, token_path: str = _DEFAULT_TOKEN_PATH) -> None:
        self._token_path = Path(token_path)
        self._status = SyncStatus()

    def _load_tokens(self) -> Dict[str, str]:
        return json.loads(self._token_path.read_text(encoding="utf-8"))

    def _get_access_token(self) -> str:
        return self._load_tokens()["access_token"]

    def is_connected(self) -> bool:
        return self._token_path.exists()

    def disconnect(self) -> None:
        if self._token_path.exists():
            self._token_path.unlink()

    def auth_url(self) -> str:
        """Return Spotify OAuth authorization URL."""
        from urllib.parse import urlencode

        from openjarvis.connectors.oauth import (
            get_client_credentials,
            get_provider_for_connector,
        )

        provider = get_provider_for_connector("spotify")
        if not provider:
            return "https://developer.spotify.com/dashboard"
        creds = get_client_credentials(provider)
        if not creds:
            return "https://developer.spotify.com/dashboard"
        client_id, _ = creds
        redirect_uri = f"http://{provider.callback_host}:{provider.callback_port}{provider.callback_path}"
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(provider.scopes),
        }
        return f"{provider.auth_endpoint}?{urlencode(params)}"

    def handle_callback(self, code: str) -> None:
        """Exchange authorization code for tokens and save."""
        from openjarvis.connectors.oauth import (
            _CONNECTORS_DIR,
            _exchange_token,
            get_client_credentials,
            get_provider_for_connector,
            save_tokens,
        )

        provider = get_provider_for_connector("spotify")
        creds = get_client_credentials(provider) if provider else None
        if not provider or not creds:
            raise RuntimeError("Spotify client credentials not configured")
        client_id, client_secret = creds
        redirect_uri = f"http://{provider.callback_host}:{provider.callback_port}{provider.callback_path}"
        tokens = _exchange_token(provider, code, client_id, client_secret, redirect_uri)
        payload = {
            "access_token": tokens.get("access_token", ""),
            "refresh_token": tokens.get("refresh_token", ""),
            "client_id": client_id,
            "client_secret": client_secret,
        }
        for filename in provider.credential_files:
            save_tokens(str(_CONNECTORS_DIR / filename), payload)

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        token = self._get_access_token()
        after_ms = int((since or datetime.now() - timedelta(days=1)).timestamp() * 1000)

        data = _spotify_api_get(
            token,
            "me/player/recently-played",
            params={"limit": "50", "after": str(after_ms)},
        )

        for item in data.get("items", []):
            track = item.get("track", {})
            played_at = item.get("played_at", "")
            artists = ", ".join(a["name"] for a in track.get("artists", []))

            ts = (
                datetime.fromisoformat(played_at.replace("Z", "+00:00"))
                if played_at
                else datetime.now()
            )

            yield Document(
                doc_id=f"spotify-{track.get('id', '')}-{played_at}",
                source="spotify",
                doc_type="recently_played",
                content=json.dumps(item),
                title=f"{track.get('name', 'Unknown')} — {artists}",
                author=artists,
                timestamp=ts,
                url=track.get("external_urls", {}).get("spotify", ""),
                metadata={
                    "track_name": track.get("name", ""),
                    "album": track.get("album", {}).get("name", ""),
                    "duration_ms": track.get("duration_ms", 0),
                },
            )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status
