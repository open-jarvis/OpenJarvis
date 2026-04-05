"""Tests for /os/brief and /os/inbox API routes.

Validates that:
1. Both endpoints return well-formed JSON with the expected keys.
2. SQLAlchemy Query objects returned by connectors are materialised
   (via ``_safe_materialise``) before being serialised or passed to
   psycopg2.  This is the root cause of the ``ProgrammingError: can't
   adapt type 'Query'`` bug.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402
from openjarvis.server.os_routes import _safe_materialise  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": "ok",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    async def mock_stream(messages, *, model, **kw):
        yield "ok"

    engine.stream = mock_stream
    return engine


@pytest.fixture
def client():
    engine = _make_engine()
    app = create_app(engine, "test-model")
    return TestClient(app)


# ---------------------------------------------------------------------------
# _safe_materialise unit tests
# ---------------------------------------------------------------------------


class TestSafeMaterialise:
    """Ensure _safe_materialise converts Query objects to plain lists."""

    def test_plain_list_unchanged(self):
        data = [1, 2, 3]
        assert _safe_materialise(data) is data

    def test_plain_string_unchanged(self):
        assert _safe_materialise("hello") == "hello"

    def test_none_unchanged(self):
        assert _safe_materialise(None) is None

    def test_dict_unchanged(self):
        d = {"a": 1}
        assert _safe_materialise(d) is d

    def test_query_object_is_materialised(self):
        """Simulate a SQLAlchemy Query object with an .all() method."""

        class Query:
            def all(self):
                return [{"id": 1}, {"id": 2}]

        q = Query()
        result = _safe_materialise(q)
        assert result == [{"id": 1}, {"id": 2}]
        assert isinstance(result, list)

    def test_query_without_all_falls_back_to_str(self):
        """If .all() is missing, fall back to str()."""

        class Query:
            def __str__(self):
                return "SELECT * FROM messages"

        q = Query()
        result = _safe_materialise(q)
        assert result == "SELECT * FROM messages"


# ---------------------------------------------------------------------------
# /os/brief endpoint tests
# ---------------------------------------------------------------------------


class TestOsBrief:
    def test_brief_returns_200(self, client):
        resp = client.get("/os/brief")
        assert resp.status_code == 200

    def test_brief_response_keys(self, client):
        data = client.get("/os/brief").json()
        assert "brief" in data
        assert "digest_meta" in data
        assert "calendar" in data
        assert "unread_counts" in data
        assert "pending_tasks" in data
        assert "generated_at" in data

    def test_brief_no_digest_returns_null(self, client):
        """When no digest is available, brief should be null."""
        data = client.get("/os/brief").json()
        # DigestStore will fail in tests (no DB), so brief is None
        assert data["brief"] is None

    def test_brief_with_digest(self, client):
        """Patch DigestStore to return a digest artifact."""
        from datetime import datetime
        from pathlib import Path

        from openjarvis.agents.digest_store import DigestArtifact

        artifact = DigestArtifact(
            text="Good morning, sir.",
            audio_path=Path(""),
            sections={},
            sources_used=["gmail", "gcalendar"],
            generated_at=datetime(2025, 12, 1, 7, 0, 0),
            model_used="qwen3:8b",
            voice_used="jarvis",
            quality_score=8.5,
        )

        mock_store = MagicMock()
        mock_store.get_latest.return_value = artifact

        with patch(
            "openjarvis.agents.digest_store.DigestStore",
            return_value=mock_store,
        ):
            data = client.get("/os/brief").json()

        assert data["brief"] == "Good morning, sir."
        assert data["digest_meta"]["model_used"] == "qwen3:8b"
        assert isinstance(data["calendar"], list)
        assert isinstance(data["unread_counts"], dict)

    def test_brief_materialises_query_from_connector(self, client):
        """Verify that a Query returned by a connector is materialised."""

        class Query:  # noqa: N801 — name must match sqlalchemy.orm.Query
            """Mimics sqlalchemy.orm.Query."""

            def all(self):
                return [{"summary": "Standup", "time": "09:00"}]

        class FakeConnector:
            def fetch(self, **kw):
                return Query()

        mock_registry = MagicMock()
        mock_registry.get.return_value = FakeConnector()

        with patch(
            "openjarvis.core.registry.ConnectorRegistry",
            mock_registry,
        ):
            # Give the app a config so the connector path is entered
            client.app.state.config = MagicMock()
            resp = client.get("/os/brief")

        assert resp.status_code == 200
        data = resp.json()
        # Calendar should contain the materialised result
        assert data["calendar"] == [{"summary": "Standup", "time": "09:00"}]


# ---------------------------------------------------------------------------
# /os/inbox endpoint tests
# ---------------------------------------------------------------------------


class TestOsInbox:
    def test_inbox_returns_200(self, client):
        resp = client.get("/os/inbox")
        assert resp.status_code == 200

    def test_inbox_response_keys(self, client):
        data = client.get("/os/inbox").json()
        assert "items" in data
        assert "total" in data
        assert "channels_queried" in data
        assert "errors" in data
        assert "generated_at" in data

    def test_inbox_empty_when_no_connectors(self, client):
        data = client.get("/os/inbox").json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_inbox_materialises_query_objects(self, client):
        """Connectors returning a Query must be materialised."""

        class Query:  # noqa: N801 — name must match sqlalchemy.orm.Query
            def all(self):
                return [
                    {"subject": "Hello", "timestamp": "2025-12-01T10:00:00"},
                    {"subject": "Meeting", "timestamp": "2025-12-01T09:00:00"},
                ]

        class FakeConnector:
            def fetch(self, **kw):
                return Query()

        mock_registry = MagicMock()
        mock_registry.get.return_value = FakeConnector()

        with patch(
            "openjarvis.core.registry.ConnectorRegistry",
            mock_registry,
        ):
            resp = client.get("/os/inbox")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 8  # 2 items × 4 channels
        # Verify items have channel tags
        channels_seen = {item["channel"] for item in data["items"]}
        assert "gmail" in channels_seen

    def test_inbox_handles_connector_errors(self, client):
        """Connector failures should be reported in errors, not crash."""

        class FailingConnector:
            def fetch(self, **kw):
                raise RuntimeError("connection refused")

        mock_registry = MagicMock()
        mock_registry.get.return_value = FailingConnector()

        with patch(
            "openjarvis.core.registry.ConnectorRegistry",
            mock_registry,
        ):
            resp = client.get("/os/inbox")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["errors"]) > 0
        assert "connection refused" in data["errors"][0]

    def test_inbox_sorts_by_timestamp(self, client):
        """Items should be sorted newest-first."""

        class FakeConnector:
            def fetch(self, **kw):
                return [
                    {"subject": "Old", "timestamp": "2025-12-01T08:00:00"},
                    {"subject": "New", "timestamp": "2025-12-01T12:00:00"},
                ]

        mock_registry = MagicMock()
        # Only return a connector for gmail, None for others
        mock_registry.get.side_effect = lambda name: (
            FakeConnector() if name == "gmail" else None
        )

        with patch(
            "openjarvis.core.registry.ConnectorRegistry",
            mock_registry,
        ):
            resp = client.get("/os/inbox")

        data = resp.json()
        assert data["total"] == 2
        assert data["items"][0]["subject"] == "New"
        assert data["items"][1]["subject"] == "Old"
