"""Tests for SpotifyConnector — Spotify Web API."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
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
                "external_urls": {
                    "spotify": "https://open.spotify.com/track/track1"
                },
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
                "external_urls": {
                    "spotify": "https://open.spotify.com/track/track2"
                },
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
