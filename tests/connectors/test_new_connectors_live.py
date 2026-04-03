"""Live smoke tests for new connectors — require real API credentials.

Run with: uv run pytest tests/connectors/test_new_connectors_live.py -v -m cloud
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from openjarvis.connectors._stubs import Document


@pytest.mark.cloud
class TestOuraLive:
    def test_sync_returns_documents(self):
        from openjarvis.connectors.oura import OuraConnector

        conn = OuraConnector()  # Uses default token path
        docs = list(conn.sync(since=datetime.now() - timedelta(days=1)))
        assert len(docs) > 0
        assert all(isinstance(d, Document) for d in docs)
        assert all(d.source == "oura" for d in docs)


@pytest.mark.cloud
class TestStravaLive:
    def test_sync_returns_documents(self):
        from openjarvis.connectors.strava import StravaConnector

        conn = StravaConnector()
        docs = list(conn.sync(since=datetime.now() - timedelta(days=7)))
        assert all(isinstance(d, Document) for d in docs)
        assert all(d.source == "strava" for d in docs)


@pytest.mark.cloud
class TestSpotifyLive:
    def test_sync_returns_documents(self):
        from openjarvis.connectors.spotify import SpotifyConnector

        conn = SpotifyConnector()
        docs = list(conn.sync(since=datetime.now() - timedelta(days=1)))
        assert all(isinstance(d, Document) for d in docs)
        assert all(d.source == "spotify" for d in docs)


@pytest.mark.cloud
class TestGoogleTasksLive:
    def test_sync_returns_documents(self):
        from openjarvis.connectors.google_tasks import GoogleTasksConnector

        conn = GoogleTasksConnector()
        docs = list(conn.sync(since=datetime.now() - timedelta(days=7)))
        assert all(isinstance(d, Document) for d in docs)
        assert all(d.source == "google_tasks" for d in docs)
