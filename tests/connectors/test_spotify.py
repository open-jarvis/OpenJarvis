"""Tests for SpotifyConnector — Spotify Web API."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from openjarvis.core.registry import ConnectorRegistry


def test_spotify_registered():
    from openjarvis.connectors.spotify import SpotifyConnector

    ConnectorRegistry.register_value("spotify", SpotifyConnector)
    assert ConnectorRegistry.contains("spotify")
    cls = ConnectorRegistry.get("spotify")
    assert cls.connector_id == "spotify"
    assert cls.display_name == "Spotify"
    assert cls.auth_type == "oauth"


_RECENTLY_PLAYED_RESPONSE = {
    "items": [
        {
            "played_at": "2026-04-01T08:30:00Z",
            "track": {
                "id": "track1",
                "name": "Bohemian Rhapsody",
                "artists": [{"name": "Queen"}],
                "album": {"name": "A Night at the Opera"},
                "duration_ms": 354000,
                "external_urls": {"spotify": "https://open.spotify.com/track/track1"},
            },
        },
        {
            "played_at": "2026-04-01T08:25:00Z",
            "track": {
                "id": "track2",
                "name": "Stairway to Heaven",
                "artists": [{"name": "Led Zeppelin"}],
                "album": {"name": "Led Zeppelin IV"},
                "duration_ms": 482000,
                "external_urls": {"spotify": "https://open.spotify.com/track/track2"},
            },
        },
    ]
}


@pytest.fixture()
def connector(tmp_path):
    from openjarvis.connectors.spotify import SpotifyConnector

    token_path = tmp_path / "spotify.json"
    token_path.write_text('{"access_token": "fake-token"}', encoding="utf-8")
    return SpotifyConnector(token_path=str(token_path))


def test_is_connected_requires_access_token(tmp_path) -> None:
    """is_connected() must check for a real access token, not just that the
    credentials file exists.

    Regression: registering a Client ID / Client Secret pair (POST /connect
    with `code: "id:secret"`) already writes the credentials file to persist
    them across the redirect to the OAuth consent screen -- before the user
    has actually authorized anything. If is_connected() only checks file
    existence, the UI's post-connect polling loop (which waits for
    `connected: true` before it stops opening/watching the consent popup)
    resolves immediately, skipping the real OAuth flow entirely. The
    connector then reports "Connected" with no access_token ever obtained,
    and the next sync crashes with `KeyError: 'access_token'`.
    """
    from openjarvis.connectors.spotify import SpotifyConnector

    creds_only_path = tmp_path / "creds_only.json"
    creds_only_path.write_text(
        '{"client_id": "abc", "client_secret": "xyz"}', encoding="utf-8"
    )
    creds_only = SpotifyConnector(token_path=str(creds_only_path))
    assert creds_only.is_connected() is False

    no_file = SpotifyConnector(token_path=str(tmp_path / "missing.json"))
    assert no_file.is_connected() is False

    with_token_path = tmp_path / "with_token.json"
    with_token_path.write_text(
        '{"client_id": "abc", "client_secret": "xyz", "access_token": "real-token"}',
        encoding="utf-8",
    )
    with_token = SpotifyConnector(token_path=str(with_token_path))
    assert with_token.is_connected() is True


def test_sync_yields_tracks(connector):
    with patch(
        "openjarvis.connectors.spotify._spotify_api_get",
        return_value=_RECENTLY_PLAYED_RESPONSE,
    ):
        docs = list(connector.sync(since=datetime(2026, 4, 1)))

    assert len(docs) == 2
    assert docs[0].source == "spotify"
    assert docs[0].doc_type == "recently_played"
    assert "Queen" in docs[0].title
    assert docs[0].metadata["track_name"] == "Bohemian Rhapsody"
