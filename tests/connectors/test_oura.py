"""Tests for OuraConnector — Oura Ring REST API v2."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


def test_oura_registered():
    """OuraConnector is discoverable via ConnectorRegistry."""
    from openjarvis.connectors.oura import OuraConnector

    ConnectorRegistry.register_value("oura", OuraConnector)
    assert ConnectorRegistry.contains("oura")
    cls = ConnectorRegistry.get("oura")
    assert cls.connector_id == "oura"
    assert cls.display_name == "Oura Ring"
    assert cls.auth_type == "token"


_SLEEP_RESPONSE = {
    "data": [
        {
            "day": "2026-04-01",
            "score": 85,
            "total_sleep_duration": 28800,
            "rem_sleep_duration": 5400,
            "deep_sleep_duration": 7200,
        }
    ]
}

_READINESS_RESPONSE = {
    "data": [
        {
            "day": "2026-04-01",
            "score": 78,
            "temperature_deviation": 0.1,
        }
    ]
}

_ACTIVITY_RESPONSE = {
    "data": [
        {
            "day": "2026-04-01",
            "score": 92,
            "steps": 8500,
            "active_calories": 450,
        }
    ]
}


@pytest.fixture()
def connector(tmp_path):
    """OuraConnector with fake token file."""
    from openjarvis.connectors.oura import OuraConnector

    token_path = tmp_path / "oura.json"
    token_path.write_text('{"token": "fake-pat"}', encoding="utf-8")
    return OuraConnector(token_path=str(token_path))


def test_is_connected(connector):
    assert connector.is_connected() is True


def test_sync_yields_documents(connector):
    """Sync returns Documents for sleep, readiness, and activity."""
    with (
        patch(
            "openjarvis.connectors.oura._oura_api_get",
            side_effect=[_SLEEP_RESPONSE, _READINESS_RESPONSE, _ACTIVITY_RESPONSE],
        ),
    ):
        docs = list(connector.sync(since=datetime(2026, 4, 1)))

    assert len(docs) == 3
    assert all(isinstance(d, Document) for d in docs)
    assert docs[0].source == "oura"
    assert docs[0].doc_type == "sleep"
    assert docs[1].doc_type == "daily_readiness"
    assert docs[2].doc_type == "daily_activity"
    assert "85" in docs[0].content  # sleep score


def test_disconnect(connector):
    connector.disconnect()
    assert connector.is_connected() is False
