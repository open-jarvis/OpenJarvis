"""Tests for StravaConnector — Strava REST API v3."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from openjarvis.core.registry import ConnectorRegistry


def test_strava_registered():
    from openjarvis.connectors.strava import StravaConnector

    ConnectorRegistry.register_value("strava", StravaConnector)
    assert ConnectorRegistry.contains("strava")
    cls = ConnectorRegistry.get("strava")
    assert cls.connector_id == "strava"
    assert cls.display_name == "Strava"
    assert cls.auth_type == "oauth"


_ACTIVITIES_RESPONSE = [
    {
        "id": 12345,
        "name": "Morning Run",
        "type": "Run",
        "sport_type": "Run",
        "start_date_local": "2026-04-01T07:30:00",
        "distance": 5200.0,
        "moving_time": 1560,
        "elapsed_time": 1620,
        "total_elevation_gain": 45.0,
        "average_heartrate": 155.0,
    },
    {
        "id": 12346,
        "name": "Evening Ride",
        "type": "Ride",
        "sport_type": "Ride",
        "start_date_local": "2026-04-01T18:00:00",
        "distance": 15000.0,
        "moving_time": 2700,
        "elapsed_time": 2900,
        "total_elevation_gain": 120.0,
    },
]


@pytest.fixture()
def connector(tmp_path):
    from openjarvis.connectors.strava import StravaConnector

    token_path = tmp_path / "strava.json"
    token_path.write_text(
        '{"access_token": "fake-token", "refresh_token": "fake-refresh"}',
        encoding="utf-8",
    )
    return StravaConnector(token_path=str(token_path))


def test_is_connected_requires_access_token(tmp_path) -> None:
    """is_connected() must check for a real access token, not just that the
    credentials file exists (see test_spotify.py for the full regression
    rationale -- same bug, same fix, applies identically to Strava)."""
    from openjarvis.connectors.strava import StravaConnector

    creds_only_path = tmp_path / "creds_only.json"
    creds_only_path.write_text(
        '{"client_id": "abc", "client_secret": "xyz"}', encoding="utf-8"
    )
    creds_only = StravaConnector(token_path=str(creds_only_path))
    assert creds_only.is_connected() is False

    no_file = StravaConnector(token_path=str(tmp_path / "missing.json"))
    assert no_file.is_connected() is False

    with_token_path = tmp_path / "with_token.json"
    with_token_path.write_text(
        '{"client_id": "abc", "client_secret": "xyz", "access_token": "real-token"}',
        encoding="utf-8",
    )
    with_token = StravaConnector(token_path=str(with_token_path))
    assert with_token.is_connected() is True


def test_sync_yields_activities(connector):
    with patch(
        "openjarvis.connectors.strava._strava_api_get",
        return_value=_ACTIVITIES_RESPONSE,
    ):
        docs = list(connector.sync(since=datetime(2026, 4, 1)))

    assert len(docs) == 2
    assert docs[0].source == "strava"
    assert docs[0].doc_type == "run"
    assert docs[0].title == "Morning Run"
    assert docs[1].doc_type == "ride"
    assert docs[0].metadata["distance_m"] == 5200.0
